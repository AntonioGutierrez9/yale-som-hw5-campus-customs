# Campus Customs Operations Dashboard – Design Notes

## Overall Design

For the dashboard, I wanted to create something that feels like a real operations center rather than just a page displaying information. My goal was to make it easy for someone managing Campus Customs to understand what is happening with each ticket, which agents are working, and what decisions still require human intervention.

I chose a design inspired by Yale's branding, using Yale blue as the main color, complemented by white and neutral tones. I wanted the interface to look professional and organized while still having some personality.

## Dashboard Layout

I organized the dashboard around the information I think would be most useful for someone running the business.

The ticket board gives a quick overview of the three open tickets and their current statuses. The live activity section shows what the agents are doing, while the approval inbox makes it easy to identify decisions that require human action. I also included the checking balance because the business has limited cash, and financial decisions affect what the agents can recommend.

I wanted to avoid having the user navigate through several pages just to understand the current situation.

## Hansome Dan Agent Avatars

Since Campus Customs is a Yale-related business, I thought it would be interesting to use Hansome Dan, Yale's bulldog mascot, to represent the five agents.

Each agent has a different accessory that reflects its responsibilities. The Boss has a tie and clipboard, Inventory has a warehouse vest and package, Accounting has glasses and a calculator, Facilities has a hard hat and wrench, and Customer Service has a headset.

I chose to keep the bulldogs in the same illustration style so they look like members of the same team, while their accessories make it easy to recognize their different roles.

## Agent Animations and Collaboration Map

One of my favorite ideas was making the bulldogs wag their tails when their agents are working.

When an agent is idle, its bulldog stays still. When it starts working, its tail begins moving. When one agent delegates to another, the connection between them is highlighted, making the collaboration visible.

I wanted this to be more than a decorative animation. By connecting it to real agent activity, someone looking at the dashboard can immediately see which agents are working and how tasks move between them.

The collaboration map also helps demonstrate that the agents work as a team rather than as five independent chatbots.

## Custom Yale Cursor

I also wanted to add a small detail that makes the dashboard feel more connected to Yale, so I chose a custom mouse cursor shaped like a capital Y in Yale blue.

The cursor is slightly larger than normal to make it more visible, but I wanted to keep it simple enough that it does not interfere with using the dashboard.

## Approval Inbox and Financial Information

I think one of the most important parts of this assignment is understanding that the agents can recommend actions, but certain decisions still require human approval.

For that reason, I wanted the approval inbox to be very visible. Each request shows why the payment or purchase is needed, how much it costs, and how it would affect the checking balance.

Showing the projected balance is particularly useful because Campus Customs has limited cash and needs to prioritize expenses.

## Ticket Timeline and Alerts

I added a timeline to make it easier to follow how each ticket progresses. Instead of only showing the final result, it displays the actions and decisions that led to that outcome.

I also wanted an attention-needed section that highlights issues such as unpaid invoices, inventory shortages, upcoming rent payments, and pending approvals.

These features help the user focus on the most important problems without having to read every agent message.

## Reset and Rerun

I included the ability to reset the working database because I wanted to be able to test the agents multiple times under the same initial conditions.

This makes it easier to compare how the system handles different tickets and verify that the agents are following the required approval process.

## Final Thoughts

Overall, I wanted the dashboard to balance functionality and creativity. The most important information should be easy to find, the approval process should be clear, and the agent activity should be transparent.

The Hansome Dan avatars and animations add a Yale identity to the project, but I also wanted them to serve a purpose by helping the user understand what the agents are doing.

My goal was to create something that would be enjoyable to use while still being practical for managing the operations of a small business.
