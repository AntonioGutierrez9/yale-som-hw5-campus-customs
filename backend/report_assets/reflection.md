Reflection – Campus Customs Multi-Agent System
1. How would I evaluate the agents' performance?
Ticket 101 – Inventory shortage
I think the agents were good at identifying the problem but inefficient at solving it. They correctly identified that the size S white tee was out of stock and that Bulldog Print Co. would not ship until its $840 invoice was paid. Accounting requested the payment, which I approved, but the tee was never restocked.
The biggest problem was the repeated delegation between Inventory and Accounting. Both reached their five-step limits without making much additional progress. The agents understood the situation, but their collaboration became unnecessarily complicated.
Ticket 102 – Rent payment
This was the most successful ticket from an execution perspective. Facilities verified the lease, Accounting prepared the $2,400 payment request, and I approved it.
I found it interesting how the sequence of tickets affected the decisions. After paying the $840 supplier invoice in Ticket 101, the business had $2,560 available. Paying rent reduced that balance to $160.
The agents handled the payment correctly and respected the approval process, although the ticket itself was never formally resolved.
Ticket 103 – Bulk hoodie order
I think the agents made reasonable financial decisions. They identified that only eight of the 20 requested hoodies were available, evaluated different discounts, and recommended 15% off.
I approved the discount, resulting in a $986 order value and a 55.4% gross margin. However, restocking the missing 12 hoodies would cost $264, and the business only had $160.
The agents correctly avoided an unaffordable purchase order. However, the Boss reached its execution limit before updating the ticket status, and Customer Service drafted the response before the discount was approved.
Overall, the financial analysis was good, but the workflow remained incomplete.
2. How did Actual compare with Expected?
Ticket 101: My original plan was sequential, with the Boss delegating to Inventory and Inventory consulting Accounting. Instead, the Boss assigned work to Inventory and Accounting simultaneously. This created overlapping work, and the two agents eventually exhausted their execution limits. The invoice was paid, but the restock was never ordered. Only two of my six planned steps were fully matched.
Ticket 102: This was relatively close to my plan, matching four of six steps. The Boss delegated directly to Facilities and Accounting rather than having Facilities delegate to Accounting. Accounting requested the payment, which I approved. Customer Service also drafted a landlord response, which I had not originally included.
Ticket 103: This followed my plan most closely, matching six of eight steps. Inventory identified the shortage, Accounting evaluated discounts and margins, and the Boss recorded the discount decision. The restock was correctly avoided because cash was insufficient. However, the customer draft was prepared before approval, and the Boss did not update the final status.
One important difference across all three tickets was that the Boss delegated tasks in parallel rather than following the sequence I had planned. I think this can make the system faster, but it also creates the risk of agents duplicating work.
Another interesting difference was that the agents sometimes chose more efficient tools than I had expected. For example, get_ticket already returned inventory, invoice, and lease information, so separate calls to list_inventory or list_invoices were not always necessary.
3. What would have been simpler with one agent?
I think Tickets 101 and 102 could have been handled more efficiently by a single agent with access to all the MCP tools.
In Ticket 101, one agent could have checked inventory, identified the unpaid invoice, evaluated the cash balance, and requested payment without repeated delegations.
Ticket 102 was even more straightforward: verify rent, check available cash, request approval, and record the payment.
Having specialized agents was more valuable for Ticket 103 because the decision involved inventory, pricing, profitability, and customer communication.
If I redesigned the system, I would use a hybrid approach: one main agent handles simple tasks and delegates only when specialized analysis is necessary.
I would also make sure the system resumes after human approvals. In this run, the agents stopped when approval was needed, but they did not automatically continue afterward. This left all three tickets without a final resolved status.
4. Three new problems the existing agents could solve
   1. Another product shortage: If a customer orders an unavailable sweatshirt size, Inventory could use list_inventory, list_vendors, and plan_restock to evaluate replenishment. Accounting could check affordability, and Customer Service could draft a response.
   2. Another bulk discount request: If a student organization wants 35 T-shirts at a discount, Accounting could use quote_bulk_order to compare profitability, Inventory could verify availability, and the Boss could use record_discount_decision to record the decision.
   3. Prioritizing competing payments: If several invoices become due around the rent payment, Accounting and Facilities could use list_invoices, get_lease, and list_approval_requests to evaluate obligations and recommend a payment priority based on available cash.
5. Three problems the agents could not solve with the existing tools
   1. Forecasting sales and cash flow: The system tracks expenses but not incoming revenue. This limited Ticket 103 because the agents could not consider future cash inflows. I would add a Sales agent with record_sale, list_sales, and forecast_cash_flow tools.
   2. Finding alternative suppliers: Ticket 101 showed how dependent the business was on Bulldog Print Co. I would add a Procurement agent with search_suppliers, request_supplier_quote, and compare_supplier_options tools to evaluate alternative prices, delivery times, and payment terms.
   3. Predicting inventory needs: The agents identified the 12-hoodie shortage but could not anticipate it. I would add an Inventory Planning agent with analyze_sales_history, forecast_product_demand, and recommend_reorder_levels tools to make purchasing more proactive.
6. Final Reflection
What surprised me most was that having more agents did not necessarily make the process more efficient. The Boss assigned tasks in parallel, which could save time, but sometimes created overlapping work and unnecessary delegation.
I also realized that the tools available to an agent can matter more than the number of agents involved. Some tools already returned enough information to make additional calls unnecessary.
From a financial perspective, I found the relationship between profitability and liquidity particularly interesting. Ticket 103 was profitable even after the discount, but the business could not afford the inventory needed to fulfill it. A profitable opportunity is not necessarily executable if the cash is unavailable.
I also think the execution limits were an important lesson. They prevented unnecessary token consumption in Ticket 101, but they also stopped the Boss from completing the final status update in Ticket 103. Finding the right balance between efficiency and completeness is important.
Although none of the tickets reached a resolved status, the system respected its safety rules: payments required human approval, no purchase orders were placed without sufficient cash, and no customer messages were actually sent.
If I improved the system, I would focus on more selective delegation, resuming workflows after human approvals, and making sure the agents complete the final administrative steps.
Overall, I think the assignment showed that multi-agent systems can support real business decisions, but they still require clear responsibilities, financial controls, and human oversight.
