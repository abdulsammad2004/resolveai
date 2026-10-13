# intent
What is the customer's latest message mainly about?
- greeting: Only says hello or opens the conversation, with no request yet.
- thanks: Only thanks the team or says goodbye, with no new request.
- knowledge_question: Asks a general question that help articles or policies could answer (shipping times, return policy, how something works).
- order_status: Asks where a specific order is, when it arrives, or for tracking.
- refund_request: Asks for money back, a refund, or a return of a specific purchase.
- cancel_order: Asks to cancel a specific order, or to change one before it ships.
- complaint: Expresses dissatisfaction with a product, delivery or the service.
- account_change: Asks to change account details, email, password, address or subscription, or reports an account access problem.
- other: Anything that fits none of the other options.

# priority
How urgently does the customer's latest message need attention?
- low: General curiosity or feedback; nothing is blocked.
- normal: A routine question or request that can wait for a normal reply.
- high: The customer is blocked, upset, or money or an order is at risk.
- urgent: Safety issue, legal threat, payment taken twice, account hacked, or the customer is locked out of their account.

# needs_human
Does this need a human agent rather than an automated answer?
- true: A person must act, decide, investigate or reassure.
- false: An automated reply or a help article answers it fully.
