# intent
What is the customer's latest message mainly about? Messages may be in any language, including Roman Urdu or a mix of languages.
- greeting: Only says hello or opens the conversation, with no request yet.
- thanks: Only thanks the team or says goodbye, with no new request.
- knowledge_question: Asks a general question about the store that help articles or policies could answer (shipping times and costs, returns, warranty, payment methods, product care).
- order_status: Asks where a specific order is, when it arrives, whether it was delivered, or for tracking; or gives the order number or email the assistant asked for.
- refund_request: Asks for money back, a refund, or to return a specific purchase, including a refund that has not arrived yet.
- cancel_order: Asks to cancel a specific order, or to change one (such as its address) before it ships.
- complaint: Expresses dissatisfaction with a product, delivery or the service, without asking for a refund or cancellation.
- account_change: Asks to change account details such as name, email, address, or newsletter and subscription settings, with no sign of a security problem.
- account_security: Account hacked or used by someone else, charges the customer did not make, password reset or two-factor (2FA) code problems, or cannot log in.
- off_topic: Unrelated to the store, its products, orders or policies, such as celebrities, news, sports, weather, trivia, homework, jokes or coding help.
- other: About the store, but fits none of the other options.

# priority
How urgently does the customer's latest message need attention?
- low: Greetings, thanks, off-topic messages, general curiosity or feedback; nothing is blocked.
- normal: A routine question or request, including an ordinary question about where an order is or a policy question.
- high: Money lost (charged twice, refund not received), an angry or upset complaint, an account or security problem, or a deadline the customer names (needed by a specific date).
- urgent: The account is hacked or being misused right now, charges the customer did not make, a safety issue or a legal threat.

# needs_human
Does this need a human agent rather than an automated answer?
- true: A person must act, decide, investigate or reassure: refunds, cancellations, complaints, account changes and every account security problem.
- false: An automated reply, an order lookup or a help article answers it fully; greetings, thanks and off-topic messages.
