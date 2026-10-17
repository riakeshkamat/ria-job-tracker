# Design System

## Purpose and scene

A graduate checks new openings at a desk in daylight, compares evidence, and opens applications. A light, restrained interface supports scanning without decorative content.

## Theme and color

Light tinted neutrals, one dark blue accent for actions and active selection. Warm text for uncertainty, green for a sponsorship mention, red for explicit restrictions. State is always expressed in words as well as color. All colors use OKLCH and are defined in `static/style.css`.

## Typography

Native system sans serif. Body and rows 14px, secondary metadata 11–12px, headings 20–26px. Roles use stronger weight; companies and timestamps remain secondary. No web font requests.

## Layout

One main column with a compact header, one-line refresh status, Jobs / Saved / Applications tabs, and a five-column semantic table. Search, role, sponsorship, and discovery-time filters are visible; work arrangement, required experience, graduate cohort, application status, and recent employer verification expand under More filters. Source counts, Plus controls, and audit views are inside Settings. Found date and experience sit under the role rather than in extra columns. Compact rows show US location options; details preserve the original source text. Smaller screens wrap filters and retain a horizontally scrollable table.

## Interaction

Native controls, visible keyboard focus, descriptive labels, and live status text. No decorative motion, charts, imagery, modals, or notification subscriptions. Opening an application never changes its status automatically.
