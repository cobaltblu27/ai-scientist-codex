---
name: heiemeier-question
description: Lay out and answer the Heiemeier/Heilmeier questions one by one for a research idea, project, or proposal.
---

# Heiemeier Question

<Purpose>
Use this skill to evaluate a research idea, project, or proposal using the Heiemeier questions, also commonly known as the Heilmeier Catechism. The agent must first lay out the questions, then answer them one by one.
</Purpose>

<Use_When>
- The user asks for Heiemeier, Heilmeier, or catechism-style evaluation explicitly.
- When this skill has been called explicitly.
</Use_When>

<Do_Not_Use_When>
- The user just wants a research idea, but hasn't invoked this skill explicitly. This skill is explicitly called usuage only.
</Do_Not_Use_When>

<Protocol>
First write the full question list. Then answer each question in order. Do not merge questions, skip questions, or answer them as a loose essay. You MUST answer every questions, and lay them out.

For every question:

- restate the question as a heading;
- answer in concrete terms;
- name unknowns or assumptions;
- say what evidence would strengthen or weaken the answer.
</Protocol>

<Questions>
1. What problem am I attacking?
2. How is it handled today?
3. What is wrong with current approaches?
4. What is my key insight?
5. What exactly will I build, prove, or measure?
6. What would convince a skeptical reviewer?
7. What is the smallest publishable version?
8. What would make this result important rather than incremental?
</Questions>

<Output_Format>
Use this structure:

```markdown
## Heiemeier Questions

1. What are you trying to do?
...
9. What are the midterm and final exams to check for success?

## Answers

### 1. What are you trying to do?
Answer:
Unknowns/assumptions:
Evidence to check:

...
```
</Output_Format>

<Quality_Bar>
Answers should be direct, falsifiable where possible, and grounded in the user's stated idea. If the idea is underspecified, make minimal assumptions and mark them clearly instead of inventing hidden context.
</Quality_Bar>
