# UI Style Guide

## 1. Positioning

This product is a **multi-agent collaboration and task management platform** for users who build and operate agents.

The interface should communicate:

- technical credibility
- operational clarity
- efficient control
- stable daily use

The right visual style is:

> **Professional developer control panel**
>  
> Clean, restrained, structured, slightly technical, and highly readable.

## 2. Style keywords

Use these keywords when designing or reviewing UI:

- professional
- calm
- efficient
- modern
- structured
- trustworthy
- technical
- high-signal

Avoid these directions:

- flashy
- playful
- futuristic-for-show
- neon cyberpunk
- excessive glass effects
- decorative over-designed visuals

## 3. Layout system

### Shell

- dark left sidebar
- light content canvas
- clear top-level page header
- generous but controlled whitespace

### Content width

- use a comfortable max-width for content-heavy edit pages
- avoid edge-to-edge form layouts when not necessary

### Grid

- use an 8px spacing system
- typical gaps: 8 / 12 / 16 / 20 / 24 / 32

## 4. Core components

### Page header

Should include:

- page title
- short supporting description when useful
- primary action on the right
- optional secondary actions

### Section card

Use section cards for grouped content.

Recommended characteristics:

- radius: 12px
- subtle border
- very light shadow or no shadow
- internal padding: 20–24px
- visible section title and optional helper text

### Buttons

#### Primary
Used for save, create, confirm, and other main actions.

#### Secondary
Used for edit, back, or less important actions.

#### Danger
Used for delete and destructive actions only.

Rules:

- do not overuse high-emphasis buttons
- one primary action per local area when possible
- keep button height consistent across the app

### Badges

Use badges for:

- status
- model
- provider
- schedule type
- environment or mode

Badge rules:

- compact
- readable
- consistent height
- semantic colors only

### Form controls

Rules:

- align labels and inputs cleanly
- keep help text quiet but readable
- use grouped sections for long forms
- keep input heights consistent
- avoid overly rounded default admin-template styling

### Tables and dense lists

Rules:

- optimize for scanning
- reduce unnecessary vertical lines
- use whitespace and alignment to separate information
- use muted headers and stronger row content
- avoid placing long paragraphs directly inside dense tables unless truncated

## 5. Typography

Recommended hierarchy:

- Page title: 28px / semibold
- Section title: 18–20px / semibold
- Field label: 13–14px / medium
- Body text: 14px
- Secondary text: 12–13px
- Tiny metadata: 12px

Rules:

- strong contrast between title, label, metadata, and body
- long descriptions should not visually compete with primary data
- use monospaced font selectively for model names, time values, git URLs, paths, or identifiers

## 6. Color strategy

Keep the palette restrained.

### Semantic colors

- primary: blue
- success: green
- warning: amber
- danger: red
- neutral: gray

### Usage rules

- use color to support meaning, not decoration
- avoid multiple competing accent colors in the same local area
- red should be rare
- warning color should be used for resets, pending states, or nearing expiration
- muted gray text should carry secondary metadata

## 7. Page-specific guidance

## 7.1 Agent list page

Current issue:
- too much flat table text
- long ability descriptions reduce scan speed
- actions feel template-like

Target:
- make the page feel like an operations panel
- let users quickly compare agents

Recommendations:
- make agent name the first visual anchor
- show provider and model as compact badges
- render status as a pill badge
- render reset timing as chips or compact stacked metadata
- truncate long ability text and provide expand/detail behavior if needed
- keep destructive action visually separated from edit

Suggested information priority:
1. name
2. status
3. model
4. expiration
5. reset timing
6. concise capability summary
7. actions

## 7.2 Edit Agent page

Current issue:
- many fields appear in one continuous block
- user must parse configuration manually

Target:
- clear configuration workflow

Recommended sections:
1. Basic information
2. Model and capability
3. Short reset policy
4. Long reset policy

Interaction recommendations:
- keep datetime + timezone visually paired
- use short helper text below fields
- place action buttons in a stable footer or bottom action bar

## 7.3 Edit Project page

Current issue:
- agent selection feels like plain checkbox rows
- selection state is weak

Target:
- make agent assignment feel intentional and understandable

Recommendations:
- use clickable selection cards
- each card should include:
  - name
  - provider
  - model
  - short ability summary
  - status
- selected state should change border, background, and check indicator
- keep the project goal input visually prominent
- keep project creation focused on name, goal, repository, participating agents, and project parameters
- do not show planning mode on the project create/edit page; planning mode belongs to the Plan page Prompt path

## 7.4 Plan page

Target:
- make the two flow sources easy to distinguish without turning the page into a wizard

Recommendations:
- use a compact full-width segmented control for "Template" vs "Prompt" source; place Template first because it is the preferred default path, and keep it visually distinct from downstream cards
- show one short dynamic helper line below the segmented control; it should change with the selected source and remain accessible to assistive technology
- in Prompt mode, show planning mode near the prompt generation controls and keep model selection visually close to each selected agent
- in Template mode, hide prompt-only controls and use a clear slot-mapping layout from template roles to project agents
- in Template mode, show the selected template's role description below each slot name as quiet secondary text; use "暂无说明" when no description exists
- disabled templates should explain the concrete reason, such as insufficient project agents
- selected template and mapped slots should remain stable while dropdown content changes

## 7.5 Process template page

Target:
- make reusable flows feel inspectable and safe to apply

Recommendations:
- list templates as scan-friendly rows or cards with name, short description, agent count, slots, and edit permission actions
- show JSON editing and DAG preview side by side on wide screens, stacked on narrow screens
- keep metadata fields explicit and place template name + applicable scenario before the prompt/JSON workflow
- allow the preview action to fill name and applicable scenario from JSON only when those fields are empty; never overwrite user-entered metadata
- after a successful preview, show role-description fields derived from JSON task assignee slots; the role count is controlled by `agent-N` slots in the JSON, not by independent add/remove controls in this section
- use clear helper text to explain that role descriptions should cover responsibility and suitable Agent type, and that users add or remove roles by editing task assignees then previewing again
- keep the DAG preview container visually stable with a fixed practical height and hidden overflow so React Flow previews do not collapse or appear blank
- use monospaced typography for task codes, slots, and output paths
- destructive delete actions should be visually separated from view/apply/edit actions

## 8. Suggested token defaults

These values are safe defaults and can be adapted to your stack.

- page background: very light gray
- surface background: white
- sidebar background: deep navy or charcoal
- primary radius: 12px
- input radius: 10px
- border color: soft neutral gray
- row height: 56–64px
- button height: 40–44px
- card padding: 20–24px

## 9. Design review checklist

Use this checklist after each redesign:

- Is the main action obvious?
- Is the information hierarchy clear in 3 seconds?
- Are repeated elements visually consistent?
- Are status, model, and timing easier to scan than before?
- Are forms grouped by user intent?
- Are long texts truncated or visually downgraded where needed?
- Does the page feel like a real product instead of a default admin template?
- Does the page still preserve current business behavior?
