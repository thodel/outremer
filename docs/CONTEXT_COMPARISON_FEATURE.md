# Context Comparison Feature

**Date:** 2026-02-24  
**Feature:** Enhanced reconciliation view with contextual information (dates, places, roles)

---

## Overview

The reconciliation view (`explorer.html`) now displays **contextual comparisons** between extracted person mentions and their candidate matches from the authority file and Wikidata. This helps reviewers make more informed decisions by showing:

- 📅 **Dates** - When the person was mentioned vs. when they lived/flourished
- 📍 **Places** - Where they were mentioned vs. their known locations/titles
- 👤 **Roles/Titles** - What role they played in the text vs. their known positions

---

## How It Works

### For Authority File Candidates

When an extracted person is matched against the Outremer authority file, the system:

1. **Extracts context** from the pipeline output:
   - `date_mention` or `context_date` - When the person appears in the text
   - `place_mention` or `toponym` - Where they're mentioned
   - `role` or `title` - What they're doing in the text

2. **Loads authority data** from `site/data/authority.json`:
   - Birth/death dates or floruit period
   - Title seat or birth place
   - Known roles and titles

3. **Displays a comparison table** showing:
   - ✅ **Green highlight** if extracted and authority data match
   - ⚠️ **Red highlight** if both have data but it conflicts
   - ➖ **Gray dash** if one side has no data

### For Wikidata Candidates

Same comparison logic applies, using Wikidata properties:
- Birth/death dates
- Birth place or location
- Occupation or title

---

## Example

```
Extracted: "Pope Urban II" (mentioned at Clermont, 1095, preaching crusade)
Authority: AUTH:CR5 - Pope Urban II (d.1099, Rome, Pope)

Context Comparison:
📅 Date       1095          →  d.1099         ✅ Match (same era)
📍 Place      Clermont      →  Rome           ⚠️ Different (but both papal contexts)
👤 Role       preaching     →  Pope           ✅ Consistent
```

---

## Technical Implementation

### Files Modified

1. **`site/app.js`** - Main application logic
   - Added `fetchAuthorityFile()` to load authority data
   - Added `buildContextComparison()` for authority matches
   - Added `buildWikidataContext()` for Wikidata matches
   - Updated `renderCandidateRow()` and `renderWikidataCandidateRow()` to display context

2. **`site/explorer.html`** - UI styles
   - Added `.context-comparison` grid layout
   - Color coding: green (match), red (mismatch), gray (partial)
   - Responsive design for mobile/desktop

### Data Flow

```
Pipeline Output (site/data/*.json)
  ↓
  link.date_mention, link.place_mention, link.role
  ↓
  buildContextComparison(link, candidate, authData)
  ↓
  HTML comparison table rendered in candidate card
```

---

## Benefits

### For Reviewers

- **Faster decisions** - See at a glance if dates/places align
- **Fewer errors** - Catch mismatches before accepting
- **Better understanding** - Learn about the historical context

### For Data Quality

- **Higher precision** - Reviewers can spot false positives
- **Richer metadata** - Encourages extraction of contextual info
- **Audit trail** - Clear why a match was accepted/rejected

---

## Usage

1. Open `site/explorer.html`
2. Select a document from the dropdown
3. Click "Load document"
4. Review each candidate match:
   - Look at the **context comparison table** below each candidate name
   - Green rows = good alignment
   - Red rows = potential mismatch (investigate further)
   - Gray rows = missing data (use judgment)

---

## Future Enhancements

Potential improvements:

1. **Hover tooltips** - Show full date ranges, not just years
2. **Map visualization** - Plot extracted vs. authority places on a map
3. **Timeline view** - Visual timeline showing mention date vs. life dates
4. **Confidence boost** - Auto-increase match score when context aligns perfectly
5. **Bulk filtering** - Filter candidates by context match quality

---

## CSS Classes

For theming/customization:

```css
.context-comparison        /* Main container */
.context-row               /* Individual comparison row */
.context-match             /* Green: data matches */
.context-mismatch          /* Red: data conflicts */
.context-partial           /* One side missing */
.context-extracted         /* Left column (from text) */
.context-candidate         /* Right column (from authority/Wikidata) */
```

---

## Testing

To test the feature:

1. Load a document with good contextual extraction (e.g., Riley-Smith 1983)
2. Find a high-confidence match like "Pope Urban II"
3. Verify the context table shows:
   - Date mentioned (1095 Council of Clermont)
   - Authority death date (1099)
   - Both should be highlighted green as compatible

---

**Status:** ✅ Implemented and deployed  
**Next steps:** Monitor user feedback, consider adding timeline visualization
