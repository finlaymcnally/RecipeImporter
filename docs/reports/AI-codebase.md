---
summary: "General report on structuring a codebase for AI-friendly discovery, safe local change, and strong boundary feedback."
read_when:
  - "When defining what 'AI-friendly' should mean before applying it to a specific repo."
  - "When planning deep-module, public-interface, or boundary-test architecture work."
---

# Report: Structuring a Codebase for Maximum AI Friendliness

## Executive summary

An AI-friendly codebase is not one that is merely “clean.” It is one that is **easy for an AI system to discover, understand, modify, and verify safely**.

The central idea behind this report is simple: **the structure of the codebase has more influence on AI output than the prompt does**. Prompts matter, but they cannot compensate for a codebase that is difficult to navigate, weakly modularized, poorly tested, or inconsistent with the mental model engineers use to understand it.

The most effective way to make a codebase AI-friendly is to treat AI as a **constant stream of new starters** joining the team. Each time an agent enters the repository, it has limited context, no lived memory of the system, and only a short window in which to understand what it should change. A codebase that works well for that kind of contributor will usually work well for humans too.

This leads to a practical conclusion: structure the codebase around **deep modules with simple, explicit interfaces**, arrange the file system so it reflects the real domain model, and build strong test and feedback loops around those module boundaries.

---

## 1. What “AI-friendly” actually means

A codebase is AI-friendly when an agent can do four things quickly and reliably:

1. **Find the relevant area of the system**
2. **Understand the public contract of that area without reading all internals**
3. **Make a local change without accidentally touching unrelated concerns**
4. **Verify the result through fast, trustworthy feedback**

If any of those steps is hard, AI output becomes weaker. The model may still generate code, but it will be more error-prone, less aligned with the architecture, and more likely to create hidden coupling or regressions.

In that sense, AI-friendliness is not mainly about clever prompting. It is about **changeability**. A codebase that is easy to change safely is also a codebase that AI can work inside more effectively.

---

## 2. The core design principle: structure should match the mental model

Most developers hold a map of the system in their head. They know that one cluster of files belongs to authentication, another to video editing, another to billing, and so on. But in many repositories, the file system does not reflect that map. Files are scattered, dependencies are loose, and modules can import from almost anywhere.

Humans can survive that because they accumulate context over time. AI cannot. It enters cold.

That is why the first rule of an AI-friendly codebase is:

**The file system and dependency structure should mirror the real conceptual structure of the product.**

If the team thinks in terms of “auth,” “video editor,” “thumbnail service,” “CMS forms,” and “billing,” then those should exist as visible, navigable units in the repository. The AI should not have to infer the architecture by stitching together dozens of loosely related files.

---

## 3. Prefer deep modules over shallow module webs

The strongest architectural recommendation is to use **deep modules**.

A deep module has:

* a **small, clear public interface**
* a **substantial internal implementation**
* **limited, deliberate points of interaction** with the rest of the system

A shallow module does the opposite. It exposes too much, does too little, and forces the reader to understand many tiny pieces at once.

For AI, shallow module webs are especially harmful. They create three problems:

### 3.1 Discoverability breaks down

The agent cannot easily tell where responsibility lives. It must scan many files to understand one feature.

### 3.2 Safe change becomes difficult

When modules are tightly interwoven, a small change can require understanding a large slice of the codebase.

### 3.3 Cognitive load explodes

The developer overseeing the AI has to keep too many relationships in mind, which creates exactly the kind of cognitive burnout the transcript warns about.

By contrast, deep modules let the AI work at the right level of abstraction. It can inspect the interface, understand the contract, and often make a change without needing to read every implementation detail.

---

## 4. Design the codebase for progressive disclosure of complexity

An AI-friendly codebase should reveal information in layers.

At the top level, the AI should see **capabilities** or **services**. Inside each service, it should see the **public interface and types**. Only after that should it need to look into internal implementation.

That is progressive disclosure:

* first: what this module does
* then: how you call it
* only then: how it works internally

This reduces unnecessary exploration and helps the AI stay aligned with intended boundaries.

A good pattern is:

```text
src/
  auth/
    public.ts
    types.ts
    README.md
    tests/
    internal/
      session-store.ts
      token-service.ts
      password-policy.ts

  billing/
    public.ts
    types.ts
    README.md
    tests/
    internal/
      invoice-calculator.ts
      tax-rules.ts
      payment-gateway.ts

  video-editor/
    public.ts
    types.ts
    README.md
    tests/
    internal/
      timeline-engine.ts
      clip-trimmer.ts
      render-queue.ts
```

In this shape, the AI can start with `public.ts`, `types.ts`, and `README.md` before it ever reads internal files.

---

## 5. Organize around business capabilities, not technical fragments

Many repositories are structured around technical layers:

```text
components/
utils/
hooks/
services/
models/
helpers/
```

This is often convenient at first, but it is poor for AI navigation because it separates things by implementation category rather than by domain responsibility.

A more AI-friendly approach is to organize by **vertical capability**:

```text
src/
  authentication/
  user-profile/
  video-editor/
  thumbnail-generator/
  content-management/
  billing/
```

Within each capability, keep the UI, domain logic, data access, and tests together where possible. That makes the module legible as a whole.

The goal is not dogma. It is clarity. The AI should be able to answer, “Where does this concern live?” with one directory, not six.

---

## 6. Treat public interfaces as first-class design artifacts

In an AI-friendly codebase, the public interface is not an afterthought. It is the main architectural seam.

That interface should be:

* **small**
* **typed**
* **explicit**
* **stable**
* **well named**
* **hard to misuse**

For example:

```ts
// src/authentication/public.ts

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthSession {
  userId: string;
  accessToken: string;
  expiresAt: Date;
}

export interface AuthenticationService {
  login(request: LoginRequest): Promise<AuthSession>;
  logout(userId: string): Promise<void>;
  validateSession(token: string): Promise<AuthSession | null>;
}
```

This tells both human and AI:

* what the module is for
* what inputs it accepts
* what outputs it returns
* where the boundary is

The implementation can change freely as long as that contract holds.

This is the ideal place for engineering judgment. The transcript’s argument is not “let AI design everything.” It is the opposite: **humans should apply taste at the boundaries**. The better the interface design, the safer the delegation of implementation work to AI.

---

## 7. Make modules gray boxes: lock behavior down with tests

The second major requirement is testing.

If deep modules are the structure, then tests are the control system.

An AI-friendly module should be a **gray box**: its internal code may be flexible, but its behavior should be constrained by tests at the boundary. That lets both humans and AI change internals with confidence.

The most useful tests in this model are:

### Boundary tests

Verify the public interface and expected behavior of the module as a whole.

### Contract tests

Check that input-output rules, error conditions, and invariants are preserved.

### Integration tests at seams

Verify the important interactions between modules, but do not overuse these to the point that feedback becomes slow.

### Fast local tests

Give immediate confirmation that a change worked. This is essential for AI because it relies heavily on short feedback loops.

The practical rule is:

**The faster and more trustworthy the feedback, the more effective the AI.**

If tests are slow, flaky, or unclear, the AI cannot reliably tell whether its changes achieved the intended effect.

---

## 8. Enforce boundaries, do not merely suggest them

An AI-friendly architecture cannot rely on convention alone.

If any file can import from any other file, the codebase will gradually collapse into accidental coupling. Humans do this under pressure; AI will do it even faster if the path is available.

Boundary rules should therefore be **enforced**, not just documented.

Examples include:

* import rules that restrict cross-module access
* visibility rules between public and internal files
* linting or build checks for dependency direction
* review standards that reject boundary violations
* ownership conventions for major modules

A healthy rule is:

**Other parts of the system may depend on a module’s public interface, but not on its internals.**

That one rule alone can dramatically improve navigability and maintainability.

---

## 9. Reduce shared “utility” sprawl

One of the most common failure modes is the uncontrolled growth of shared code:

```text
utils/
common/
helpers/
shared/
misc/
```

These directories become architectural junk drawers. They attract unrelated logic, leak abstractions across the system, and erase boundaries between domains.

For AI, they are especially dangerous because they look reusable and easy to import, even when they encode hidden assumptions.

A better approach is:

* keep helpers close to the module that owns them
* promote something to shared status only when it has a clear, stable, cross-domain purpose
* give shared code explicit ownership and a narrow interface

In other words, do not make it easy for AI to solve a local problem by creating a global dependency.

---

## 10. Plan changes in terms of modules, interfaces, and tests

The transcript makes an important process point: this architecture should influence work from the planning stage onward.

That means PRDs, tickets, and implementation plans should ask:

* Which module is being changed?
* Is this a new module or an extension of an existing one?
* Does the public interface change?
* What tests will verify the behavior?
* What boundaries must remain intact?

This changes how teams write work items. Instead of “add feature X,” a stronger task is:

> Extend the `thumbnail-generator` module to support template presets.
> Keep the public interface backward compatible.
> Add boundary tests for preset selection and image output validation.

That framing is easier for both humans and AI to execute cleanly.

---

## 11. What to avoid

An AI-friendly codebase should actively avoid these patterns:

### A web of tiny interconnected modules

This increases navigation cost and makes local reasoning difficult.

### File structures that do not match the domain

The AI should not need to reverse-engineer the architecture.

### Interfaces that leak implementation details

Public contracts should stay small and intention-revealing.

### Slow or flaky tests

Weak feedback destroys AI reliability.

### Cross-feature imports into internals

This creates hidden coupling and defeats modularity.

### Overgrown shared directories

These become dependency magnets and confuse ownership.

### Naming that assumes insider context

AI benefits from direct, descriptive names more than clever ones.

---

## 12. A practical target architecture

A strong default model is:

```text
src/
  feature-a/
    README.md
    public.ts
    types.ts
    tests/
    internal/

  feature-b/
    README.md
    public.ts
    types.ts
    tests/
    internal/

  shared-kernel/
    logging/
    error-handling/
    primitives/

  app/
    composition/
    routing/
    boot/
```

### How this works

* **Feature folders** are the main units of change.
* **`public.ts`** defines the only supported entry point.
* **`types.ts`** clarifies the contract.
* **`README.md`** gives a short explanation of purpose, invariants, and usage.
* **`internal/`** holds implementation details not intended for outside access.
* **`tests/`** lock down module behavior.
* **`app/composition`** wires modules together without dissolving their boundaries.

This creates a repository that is easy to scan, easy to reason about, and easy for AI to operate inside.

---

## 13. Migration approach for an existing codebase

Most teams cannot redesign the whole repository at once. The practical approach is incremental.

### Step 1: Map the real domain structure

Write down the major capabilities your team already thinks in.

### Step 2: Find high-change, high-pain areas

These are the best candidates for refactoring into deep modules first.

### Step 3: Define a clean public interface

Do not start by moving every internal file. Start by clarifying the boundary.

### Step 4: Add boundary tests

Make behavior stable before broad internal changes.

### Step 5: Move implementation behind the interface

Hide internals and reduce uncontrolled imports.

### Step 6: Enforce dependency rules

Prevent the old shape from re-forming.

### Step 7: Repeat module by module

Over time, the architecture becomes more legible and more AI-friendly.

---

## Conclusion

To make a codebase AI-friendly, do not begin with prompts. Begin with architecture.

The ideal repository is one where the file system matches the product’s real conceptual structure, where each major capability is represented by a deep module, where public interfaces are small and deliberate, where internals are hidden behind those interfaces, and where tests provide fast, trustworthy feedback at the module boundary.

That is not a new theory. It is established software engineering applied under new conditions.

The difference is that AI raises the cost of bad structure and increases the value of good structure. A messy codebase can still function for a human team that carries years of accumulated context. It performs much worse when every coding session effectively introduces another stateless newcomer.

The most AI-friendly codebase is therefore also a highly maintainable human-friendly codebase: modular, navigable, explicit, and testable.

I can also turn this into a one-page engineering policy or a team checklist for code reviews.
