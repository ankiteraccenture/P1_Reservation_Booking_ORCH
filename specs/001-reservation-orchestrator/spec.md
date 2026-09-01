# Feature Specification: Reservation & Booking Orchestrator (Hold → Pay → Confirm → Cancel)

**Feature Branch**: `001-reservation-orchestrator`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Build a spec-driven service that searches flights & rooms, applies dynamic pricing, and runs a reliable hold → pay → confirm → cancel lifecycle — an orchestrator delegating to pricing, booking & payment subagents. Guests abandon bookings when pricing is slow/inconsistent and holds don't expire cleanly."

## Clarifications

### Session 2026-09-01

- Q: Should the 15-minute hold window be a single fixed value for every offer in v1, or must it vary by offer type or by channel? → A: Single global 15-minute hold applies to every offer and every channel in v1; not runtime-configurable.
- Q: When a guest or partner cancels a confirmed and paid reservation, must the created refund request always be for the full paid amount, or should the caller be able to request a partial refund? → A: Refund amount is set automatically by a cancellation policy, not by the caller. For **room** reservations: full refund if the cancellation occurs 48 hours or more before the check-in date; otherwise the equivalent of one night's charge (base nightly rate for the first night, in the reservation's currency) is retained and the remainder is refunded. For **flight** reservations in v1: the refund amount follows the underlying provider's cancellation terms as returned by the provider adapter; the operator still approves under the human gate.
- Q: When the payment provider does not respond within its timeout during the pay step of the saga, what terminal state should the reservation land in after the retry budget is exhausted? → A: Release the hold, mark the reservation `CANCELLED_PAYMENT_FAILED`, emit a `payment.failed` domain event, and instruct the guest to start a new hold and retry payment. No provider refund is requested unless a capture was actually confirmed; any authorized-but-unconfirmed funds are handled by the payment provider's own authorization expiry.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Guest search → quote → hold → pay → confirm (Priority: P1)

A guest opens the booking experience, enters travel dates and occupancy, and searches. The system returns a single, unified list of available flight and room offers with a firm, dynamically calculated price shown per offer. The guest selects an offer, places a short-lived hold that locks the inventory, pays within the hold window, and receives a confirmed reservation with a confirmation reference.

**Why this priority**: This is the MVP slice. It directly addresses the core problem — guests abandoning bookings due to slow or inconsistent pricing and unreliable holds. Without this path working end to end, no other journey delivers value.

**Independent Test**: Simulate a guest booking flow end to end with stubbed inventory: submit a search, verify a quote is returned and stable across re-quotes within the hold window, place a hold, complete payment, and verify the reservation reaches a confirmed state with an audit trail of every transition.

**Acceptance Scenarios**:

1. **Given** valid travel dates and occupancy, **When** the guest submits a search, **Then** the system returns a merged, deduplicated list of flight and room offers, each with a firm quoted price and currency, ordered by relevance and price.
2. **Given** a selected offer, **When** the guest places a hold, **Then** the offer's inventory is locked, a hold record is created with an explicit expiry (15 minutes from creation), and the guest sees the remaining hold time.
3. **Given** an active hold, **When** the guest completes payment before expiry, **Then** the reservation transitions to a confirmed state, a confirmation reference is returned, and the guest receives a confirmation notification.
4. **Given** a completed search, **When** the same search is repeated within the pricing stability window, **Then** the quoted price for each returned offer is identical, and any deviation is recorded with a reason.

---

### User Story 2 - Cancel a held or paid reservation (Priority: P2)

A guest (or a partner acting on the guest's behalf) cancels a reservation that is either still on hold or already paid. The system releases the locked inventory immediately. If the reservation was already paid, the system computes the refundable amount from the cancellation policy (rooms: full refund if the cancellation is 48 hours or more before check-in, otherwise the first night's base rate is retained; flights: the provider's returned refundable amount) and records a refund request for that amount. The request enters the approval queue and the refund is not executed automatically.

**Why this priority**: Cancellation is a table-stakes capability. Without it, holds block inventory and paid guests have no self-service exit path, both of which erode trust and revenue.

**Independent Test**: Create a held reservation and cancel it — verify inventory is released and no refund is created. Separately, create a paid **room** reservation and cancel it 72 hours before check-in — verify a full-amount refund request is created; cancel a second paid room reservation 24 hours before check-in — verify a partial refund request equal to (total paid − first night's base rate) is created. For a paid **flight** reservation, verify the refund request amount equals the provider adapter's returned refundable amount. In all paid cases, verify inventory is released and no provider refund is issued until an approver acts.

**Acceptance Scenarios**:

1. **Given** an active hold, **When** the guest or partner cancels it, **Then** the hold is released, inventory is available for other guests, and the reservation is marked cancelled with a timestamp and reason.
2. **Given** a confirmed and paid room reservation whose check-in is at least 48 hours away, **When** the guest or partner cancels it, **Then** inventory is released, the reservation is marked cancelled, and a refund request is created for the full paid amount in the reservation's currency.
3. **Given** a confirmed and paid room reservation whose check-in is less than 48 hours away, **When** the guest or partner cancels it, **Then** inventory is released, the reservation is marked cancelled, and a refund request is created for the paid amount minus one night's base rate (never less than zero).
4. **Given** a confirmed and paid flight reservation, **When** the guest or partner cancels it, **Then** inventory is released, the reservation is marked cancelled, and a refund request is created for the amount the provider adapter reports as refundable under the provider's cancellation terms.
5. **Given** a cancellation attempt with the same client-supplied idempotency key as a prior attempt, **When** it is submitted again, **Then** the system returns the original outcome without duplicating any state changes.

---

### User Story 3 - Operator approves refund via four-eyes (Priority: P3)

A support or finance operator opens the refund approval queue, reviews the reservation context (original charge, prior refunds, remaining refundable balance), and either approves or rejects the refund. Only after an approver distinct from the requester approves is the refund executed with the payment provider.

**Why this priority**: Refunds move real money out of the business and are a well-known vector for fraud and operational error. This journey is required by the project constitution's human-in-the-loop refund gate and is a compliance-facing capability.

**Independent Test**: Seed a pending refund request created by user A. Attempt to approve it as user A — verify it is refused. Approve it as user B holding the approver permission — verify the refund is executed with the (stubbed) payment provider, the reservation's refund state advances to executed, and an immutable audit record captures both actors.

**Acceptance Scenarios**:

1. **Given** a pending refund request created by user A, **When** user A attempts to approve it, **Then** the approval is rejected with a clear "self-approval not permitted" reason and no provider call is made.
2. **Given** a pending refund request created by user A, **When** user B with the approver permission approves it, **Then** the refund is executed exactly once, the reservation's refund state advances to executed, and an audit record captures actor identities, timestamps, amount, currency, and reason.
3. **Given** an approved-but-not-yet-executed refund, **When** an operator revokes the approval before execution, **Then** the refund is not executed and the request returns to a pending state.

---

### User Story 4 - Hold auto-expiry releases inventory (Priority: P2)

An unpaid hold reaches its 15-minute deadline. The system automatically releases the locked inventory, marks the reservation as cancelled due to expiry, and emits an event so downstream consumers (analytics, notifications) can react.

**Why this priority**: Reliable expiry is the other half of "holds don't expire cleanly." Without it, inventory silently rots and the search experience becomes wrong. It ties directly to Success Criterion SC-003.

**Independent Test**: Create a hold, do not pay, advance the clock past the 15-minute deadline, and verify that within 60 seconds the reservation is cancelled, the inventory is released, and a `hold.expired` event has been emitted.

**Acceptance Scenarios**:

1. **Given** a hold whose expiry deadline has passed and no payment has been made, **When** the expiry process runs, **Then** the reservation is marked cancelled with reason "expired", inventory is released, and a `hold.expired` event is emitted within 60 seconds of the deadline.
2. **Given** a hold whose deadline is approaching, **When** payment is completed before the deadline, **Then** the expiry process does not cancel the reservation and no `hold.expired` event is emitted.

---

### User Story 5 - Partner channel books programmatically with idempotency (Priority: P3)

A partner channel (B2B API caller) drives the same search → hold → pay → confirm and cancel flows programmatically. Every state-changing call carries a client-supplied idempotency key, and retries never produce duplicate holds, duplicate payments, or duplicate cancellations.

**Why this priority**: Partner traffic amplifies both revenue and error surface area. Idempotency is required by the project constitution and is the only reliable defense against retries under network failures.

**Independent Test**: Issue the same hold request twice with the same idempotency key — verify one hold is created and the second call returns the original outcome. Repeat for payment and cancellation.

**Acceptance Scenarios**:

1. **Given** two identical hold requests sharing an idempotency key, **When** both are received, **Then** exactly one hold is created and both callers receive the same response.
2. **Given** two identical payment requests sharing an idempotency key, **When** both are received, **Then** exactly one payment is captured and both callers receive the same response.
3. **Given** two identical cancel requests sharing an idempotency key, **When** both are received, **Then** the reservation is cancelled exactly once and both callers receive the same response.

---

### Edge Cases

- What happens when a search returns zero available offers for the requested dates and occupancy? — the system returns an explicit empty result with a reason, not an error.
- What happens when a second guest attempts to hold an item that another guest has just held? — the second hold is rejected with a "not available" reason (no double-booking).
- What happens when the payment provider times out mid-capture? — the reservation stays in a defined intermediate state, the operation is safely retriable with the same idempotency key, and once the retry budget is exhausted without a confirmed capture the reservation transitions to the terminal state `CANCELLED_PAYMENT_FAILED`, the hold is released, and a `payment.failed` event is emitted (see FR-015a).
- What happens when a hold's expiry job runs after payment has already succeeded? — the expiry job detects the state change and takes no action.
- What happens when a refund is requested for an amount greater than the remaining refundable balance? — the request is rejected before it enters the approval queue.
- What happens when the search hits a temporary provider outage on one channel (flights or rooms)? — the response includes results from the healthy channel plus a documented partial-result indicator, rather than failing the whole search.
- What happens when the same reservation receives simultaneous cancel and pay requests? — the system serializes the transitions and rejects the losing operation with a clear conflict reason.
- What happens when a guest closes their browser between hold and pay? — the hold continues counting down and expires normally; no manual cleanup is required.

## Requirements *(mandatory)*

### Functional Requirements

**Search & pricing**

- **FR-001**: The system MUST accept a search request containing travel dates and occupancy and return a single merged list of available flight and room offers.
- **FR-002**: The system MUST return only rooms available for the full requested date range (no partial-availability rooms).
- **FR-003**: The system MUST attach a firm quoted price and a currency to every returned offer.
- **FR-004**: The system MUST apply pricing rules in a deterministic, documented order: season → occupancy surge → length-of-stay discount → tier discount, so identical inputs and rule set always yield identical prices.
- **FR-005**: The system MUST persist, for every quote, the inputs and each rule's contribution to the final price so any quote can be audited after the fact.
- **FR-006**: The system MUST expose a stable quoted price for the duration of the hold window; any deviation MUST be recorded with a reason and surfaced to the caller.

**Hold lifecycle**

- **FR-007**: The system MUST allow a guest or partner to place a hold on an offer that locks the underlying inventory.
- **FR-008**: A hold MUST have an explicit expiry set to a single global 15-minute window from the moment of creation, applied uniformly across all offer types (flights, rooms) and all channels (guest, partner); the window is not runtime-configurable in v1.
- **FR-009**: The system MUST reject a hold attempt on inventory already held or booked by another party.
- **FR-010**: The system MUST automatically release inventory and mark the reservation cancelled when an unpaid hold passes its expiry deadline, within 60 seconds of expiry.
- **FR-011**: The system MUST emit a `hold.expired` domain event when an expiry-driven cancellation occurs.

**Payment & confirmation**

- **FR-012**: The system MUST allow the guest to pay for a held reservation before the hold expires.
- **FR-013**: A successful payment MUST transition the reservation to a confirmed state and return a confirmation reference.
- **FR-014**: The system MUST send the guest a confirmation notification when a reservation is confirmed.
- **FR-015**: The system MUST reject payment attempts against expired, cancelled, or already-paid reservations with an explicit reason.
- **FR-015a**: When the payment provider fails to confirm a capture within the payment step's timeout and the retry budget is exhausted, the system MUST transition the reservation to the terminal state `CANCELLED_PAYMENT_FAILED`, release the hold, emit a `payment.failed` domain event carrying the correlation identifier and the last provider error, and return an explicit "payment failed, please start a new hold and retry" response to the caller. The system MUST NOT issue a refund request in this path unless a capture was confirmed by the provider; any authorized-but-unconfirmed funds are left for the provider's own authorization expiry to release.

**Cancellation**

- **FR-016**: The system MUST allow a guest or partner to cancel a reservation that is on hold or confirmed.
- **FR-017**: Cancelling a held (unpaid) reservation MUST release its inventory and mark it cancelled without creating a refund.
- **FR-018**: Cancelling a confirmed (paid) reservation MUST release its inventory, mark the reservation cancelled, and create a refund request in a pending-approval state that references the original payment and carries a system-computed refundable amount (see FR-018a and FR-018b). The caller MUST NOT supply the refund amount.
- **FR-018a**: For **room** reservations, the refundable amount MUST be computed as: the full paid amount if the cancellation timestamp is 48 hours or more before the check-in date (in the property's local time zone); otherwise the paid amount minus one night's base rate (the base nightly rate for the first night of the stay, in the reservation's currency). The resulting amount MUST NOT be negative; if the computation would produce a negative value it MUST be clamped to zero and the request MUST still be created (for audit) with amount zero.
- **FR-018b**: For **flight** reservations, the refundable amount MUST be the value returned by the flight provider adapter's cancellation-quote call under the provider's own cancellation terms. If the provider adapter is unavailable, the refund request MUST NOT be created and the cancellation MUST be rejected with a retriable "refund quote unavailable" reason (inventory release still succeeds).

**Refund gate (human-in-the-loop)**

- **FR-019**: The system MUST NOT execute any refund with the payment provider unless a persisted approval record exists for that refund.
- **FR-020**: The approver of a refund request MUST be a different principal than the requester (four-eyes); self-approval MUST be rejected.
- **FR-021**: The system MUST permit only principals holding the `payments:refund:approve` permission to approve refund requests.
- **FR-022**: The system MUST persist an immutable audit record for every refund state transition, capturing actor identity, actor role, timestamp, amount, currency, reason code, and free-text justification.
- **FR-023**: The system MUST permit an approved refund to be revoked before it is executed and MUST NOT execute revoked refunds.
- **FR-024**: The system MUST reject a refund request whose amount exceeds the remaining refundable balance.
- **FR-025**: The auto-refund allowlist MUST be empty at launch; adding an entry requires a governed policy change.

**Idempotency & consistency**

- **FR-026**: Every state-changing operation (hold, pay, cancel, refund request, refund approve, refund execute) MUST accept a client-supplied idempotency key.
- **FR-027**: Repeated calls with the same idempotency key within the deduplication window (at least 24 hours) MUST produce exactly one effect and return the original response.
- **FR-028**: The system MUST never leave a reservation in an unknown state after a transient failure; every failed transition MUST resolve to a defined, reconcilable state.

**Auditability & events**

- **FR-029**: The system MUST record every state transition of every reservation (created, held, paid, confirmed, cancelled, refund-requested, refund-approved, refund-executed) with actor, timestamp, and reason.
- **FR-030**: The system MUST emit domain events for reservation created, hold expired, booking confirmed, cancellation completed, payment authorized, payment failed, refund requested, refund approved, and refund executed.

**Authentication & authorization**

- **FR-031**: The system MUST authenticate every caller — guest, operator, and partner — before permitting any state-changing action.
- **FR-032**: The system MUST enforce that only guests (or partners acting on their behalf) can create holds, payments, and cancellations for the reservations they own; operators can only view and act on the refund approval queue within their permission scope.

**Money handling**

- **FR-033**: All monetary values MUST be represented and stored with an explicit currency and a decimal type; float arithmetic on money is prohibited.
- **FR-034**: For v1, the supported currency is USD only; a request in any other currency MUST be rejected with a clear "currency not supported" reason.

### Key Entities

- **SearchQuery**: what the guest is looking for — travel dates, occupancy, channel(s), currency.
- **Offer**: a normalized, quotable item from a provider — provider reference, kind (flight or room), availability window, quoted price with currency, quote breakdown.
- **Reservation**: the guest-facing booking record with an explicit lifecycle state (new → held → paid → confirmed → cancelled | cancelled_payment_failed and, when applicable, refund_requested → refund_approved → refund_executed), an owning customer, a linked offer, and audit metadata.
- **Hold**: the time-boxed lock on inventory attached to a reservation, with creation time and 15-minute expiry.
- **Payment**: the money-movement record for a reservation, referencing the payment provider identifier, amount, currency, and status.
- **Refund**: the request-to-reverse-a-payment record, referencing the originating payment, requested amount, currency, requester, approver (once assigned), state, and reason.
- **AuditEvent**: an append-only record of a state transition, capturing actor identity, actor role, timestamp, correlation identifier, and reason.
- **IdempotencyRecord**: the durable dedup entry that binds a client-supplied idempotency key to the resulting response for at least 24 hours.
- **PricingRule**: a declarative rule contributing to a quote (season, occupancy surge, length-of-stay discount, tier discount), evaluated in a documented order.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Guests see the first quote within 800 ms at the 95th percentile from the moment a search is submitted, under nominal load.
- **SC-002**: Hold-to-pay conversion improves by at least 15 percentage points over the pre-launch baseline within 60 days of launch.
- **SC-003**: Zero holds remain in an unresolved state beyond their 15-minute expiry plus a 60-second grace window during any rolling 24-hour period.
- **SC-004**: 100% of executed refunds have a matching approval record whose approver is distinct from the requester; zero refunds are executed without such a record.
- **SC-005**: The reservation service (search, hold, pay, cancel) is available for at least 99.9% of every calendar month.
- **SC-006**: When the same search inputs are submitted twice within the hold window, both quotes are identical for 100% of offers in a 1000-search sample.
- **SC-007**: No two guests are ever confirmed for the same underlying inventory (double-booking rate = 0) across all traffic.
- **SC-008**: A repeated hold, pay, or cancel request bearing the same idempotency key produces exactly one effect in 100% of a 1000-request replay test.
- **SC-009**: Self-approval attempts on refunds are rejected in 100% of a 200-attempt sample; no provider refund call is issued for a rejected attempt.
- **SC-010**: 95% of confirmed guests receive their confirmation notification within 30 seconds of confirmation.
- **SC-011**: For a synthetic 500-cancellation sample of paid room reservations spanning both sides of the 48-hour cutoff, the computed refundable amount matches the policy exactly in 100% of cases (full refund at ≥48h; paid amount minus first night's base rate inside 48h).
- **SC-012**: In a chaos test that injects a payment-provider timeout on 100 pay attempts after retry-budget exhaustion, 100% of the affected reservations end in the `CANCELLED_PAYMENT_FAILED` terminal state with the hold released and a `payment.failed` event emitted; zero reservations end in an undefined or "unknown" state.

## Assumptions

- One flight-provider stub and one room-provider stub are sufficient for v1; onboarding real providers is out of scope.
- Single currency (USD) for v1; multi-currency is a follow-on.
- Guests and operators authenticate through the platform's existing identity provider; operators are distinguished by a dedicated approver permission.
- The React-based first-party UI is the sole guest and operator surface for v1; partner integrations use the programmatic API.
- The hold expiry window is 15 minutes for v1 and is not per-offer configurable.
- Notifications are email-based for v1; SMS and push are follow-ons.
- Cancellation policy for v1 is: unpaid holds cancel free; for paid **room** reservations, a cancellation 48 hours or more before check-in is fully refundable and inside 48 hours retains one night's base rate; for paid **flight** reservations, the refundable amount is whatever the flight provider adapter reports under the provider's own cancellation terms. Every paid cancellation still requires operator approval before the provider refund is executed.
- The auto-refund allowlist ships empty; every refund goes through the human gate at launch.

## Dependencies

- An identity provider capable of issuing tokens for guests, partners, and operators, and of representing the operator approver permission.
- A payment provider capable of authorization, capture, and refund, with idempotent APIs.
- A notification channel capable of delivering confirmation and cancellation messages to guests.
- A durable clock source and a scheduler capable of reliably triggering hold-expiry processing.

## Out of Scope (v1)

- Multi-currency pricing and settlement.
- Multi-tenant billing or channel-specific pricing.
- Loyalty programs, seat maps, ancillary upsell, group bookings.
- Offline mode or store-and-forward guest flows.
- Auto-refund policies (the allowlist ships empty).
- Partial refunds and multi-installment refunds.
- Real provider onboarding beyond the two v1 stubs.
