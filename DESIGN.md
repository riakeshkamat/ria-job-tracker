# Design System

## Purpose and scene

A graduate checks new openings at a desk in daylight, compares evidence, and opens applications. A light, restrained interface supports scanning without decorative content.

## Theme and color

Light tinted neutrals, one dark blue accent for actions and active selection. Warm text for uncertainty, green for a sponsorship mention, red for explicit restrictions. State is always expressed in words as well as color. All colors use OKLCH and are defined in `static/style.css`.

## Typography

Native system sans serif. Body and rows 14px, secondary metadata 11–12px, headings 20–26px. Roles use stronger weight; companies and timestamps remain secondary. No web font requests.

## Layout

One main column with a header, refresh status, view tabs, filters, and a semantic table. Source health and Plus settings expand inline. Job evidence and notes expand directly beneath their row. Smaller screens wrap filters and retain a horizontally scrollable table.

## Interaction

Native controls, visible keyboard focus, descriptive labels, and live status text. No decorative motion, charts, imagery, modals, or notification subscriptions. Opening an application never changes its status automatically.
