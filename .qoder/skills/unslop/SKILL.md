---
name: unslop
description: Unified auditor for AI-generated aesthetics. Menu-driven skill that routes to the right unslop domain (UI/text/code) or runs all three. Detects and removes telltale patterns that scream "AI-generated."
license: MIT
---

# Unslop — Unified AI-Generated Aesthetics Auditor

**What this does:** Detects and strips "tells" (telltale signs) that make content look like it was created by AI. Routes to the right auditor based on what you're checking.

## How to use

When you invoke this skill, follow the menu. **Tell me what you're auditing:**

1. **UI/Website** — visual design patterns
2. **Text/Writing** — prose patterns and word choices
3. **Code** — source code artifacts and structure
4. **All three** — comprehensive audit across all domains

---

## 📊 What Each Auditor Does

### 1. Unslop UI — Website Design
Detects and removes visual AI tells in web design:
- **Shadcn/Tailwind defaults** — cookie-cutter component libraries
- **AI-purple gradients** — pervasive neon/purple color schemes
- **Gradient hero text** — that flashy text effect
- **Neon glow effects** — unprompted glowing elements
- **Emoji-as-icons** — lazy iconography
- **Centered hero + cards** — the "three cards below a hero" layout

**Use when:** You're auditing website design, landing pages, or UI mockups.

---

### 2. Unslop Text — Writing
Detects and removes prose patterns that read as machine-generated:
- **Em dashes** — overused em dashes connecting thoughts
- **"It's not just X, it's Y"** — that specific cadence
- **Assistant boilerplate** — leftover "how can I help" language
- **Sycophantic openers** — overly praise-y intros
- **Delve/leverage diction** — corporate buzzwords
- **"In conclusion" wrap-ups** — formal essay-style endings
- **Placeholder language** — generic filler phrases

**Use when:** You're auditing blog posts, documentation, copy, or any prose.

---

### 3. Unslop Code — Source Code
Detects and removes code artifacts that indicate AI authorship:
- **Leftover chat comments** — "Here's the implementation:" style comments
- **Placeholder comments** — "// TODO: implement" left in
- **Emoji in code** — 🎉 and other emoji scattered in source
- **Swallowed errors** — empty `try/except` blocks
- **Narrating comments** — comments explaining what code obviously does
- **Generic placeholder names** — `data`, `result`, `process()`, `item`
- **Boilerplate** — vast uninspired starter templates
- **Hallucinated APIs** — calls to functions that don't exist
- **Structural issues** — patterns that only linters usually miss

**Use when:** You're auditing source code, scripts, or generated implementations.

---

## 🚀 How It Works

### When you choose one auditor (UI, Text, or Code):
I'll analyze your content and flag the tells, showing you:
1. **What it flagged** — which specific patterns detected
2. **Why it's a tell** — what makes it scream "AI-generated"
3. **How to fix it** — concrete suggestions to strip the tells
4. **Rewritten version** — your content with tells removed (when applicable)

### When you choose "All three":
I'll run a comprehensive audit across all domains (useful if you've got a full website or multi-format project), then summarize findings by category.

---

## 📋 Quick Guide

| You're auditing… | Choose this |
|---|---|
| A website landing page | **UI** |
| A blog post or article | **Text** |
| Python/JS/Go source code | **Code** |
| A full project (all of the above) | **All three** |

---

## 🎯 Next Step

**What are we auditing?** Reply with one of:
- `UI` — website design
- `Text` — writing/prose
- `Code` — source code
- `All three` — everything

Then paste your content and I'll detect the tells.
