# Comment #1: 
I now have a million lines of code (about 40% of that is tests) in the thing I've been building for about 6 months.

I am finding much better ways to get code quality very high now.

The main thing for me is using the type system (working in typescript) in an obsessive way - I get Claude/codex to "imagine you're a Haskell developer who has been forced to write typescript. Use the type system obsessively to prevent classes of bugs. Have unusually high standards for encoding business logic in the type system.".

Everything that touches the DB has integration tests. Every semi important user flow has playwright tests.

I have lint rules that force certain architectures - a type-safe endpoint definition that encodes the payload the route accepts, the response shape, which errors a route can throw, and forces all of these to be handled. A typed API client that can only take an endpoint type and has to handle all possible errors and must accept the correct response shape.

Typescript settings are strict and getting stricter - no implicit any, no explicit any, a bunch of other rules.

This has slowed down the act of agents writing code somewhat, but development is faster - llms get immediate feedback when they run the verify script (which lints, typechecks, builds, runs tests), so many bugs are caught before they get to me.

Even with this, every large feature normally needs a bigger architectural refactor after it's "complete". The llms take care of this - I ask them to consider the code they wrote, consider FP principles and type safety (again with that obsessive lens), and suggest any ways we can make code more purely functional, more testable, more type safe, easier to reason about. They generally make great suggestions.

I'm getting fewer and fewer bugs, but still some. I'm planning to keep pushing the type safety thing even further, for me it's the key. If the Haskell ecosystem was fuller, I think it would be perfect for llm assisted dev - the "if it compiles, it runs" thing is real. I'm just trying to do the poor man's version of that with TS.

# Comment #2:
Create documentation with a summary of where things are and what they do, and directing the agent to look there first so it doesn't go rampant looking for things where they should not be.

My code is at around 200k lines right now. The agent can tell exactly what and how my codes does what it needs by reading less than 5% of that (and that's for understanding the ENTIRE thing), if it just needs understand a specific thing, that % drops 0.xxxxx values.