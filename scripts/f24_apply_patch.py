from pathlib import Path


def require_replace(text: str, old: str, new: str, name: str) -> str:
    if old not in text:
        raise SystemExit(f"anchor not found: {name}")
    return text.replace(old, new, 1)


raster = Path("pb_raster_schedule_extractor.py")
text = raster.read_text(encoding="utf-8")
if "from pb_opening_tag_normalization import normalize_opening_tag" not in text:
    text = require_replace(
        text,
        "import fitz\n",
        "import fitz\n\nfrom pb_opening_tag_normalization import normalize_opening_tag\n",
        "fitz import",
    )

old_table = '''                    # Determine trade type
                    combined_text = f"{raw_tag} {raw_desc} {raw_dim}".lower()
                    trade = "other"
                    if any(k in combined_text for k in ("window", "casement", "glaz", "w1", "w2", "w3", "w4")):
                        trade = "windows"
                    elif any(k in combined_text for k in ("door", "flush", "panelled", "d1", "d2")):
                        trade = "doors"
                    elif any(k in combined_text for k in ("vent", "pv")):
                        trade = "walls"
                    elif any(k in combined_text for k in ("pillar", "column", "pier", "truss")):
                        trade = "structure"

                    # Only accept recognized architectural trade tags, skip generic non-schedule items
                    if trade == "other" or not raw_tag or raw_tag.startswith("ITEM_") or raw_tag.isdigit():
                        continue
                    tag_name = raw_tag
'''
new_table = '''                    # Normalize only an explicitly documented opening identity.
                    # Dimensions never imply W/D tags.
                    normalized_opening = normalize_opening_tag(raw_tag)
                    combined_text = f"{raw_tag} {raw_desc} {raw_dim}".lower()
                    trade = normalized_opening.trade_type if normalized_opening else "other"
                    if trade == "other" and any(k in combined_text for k in ("window", "casement", "glaz")):
                        trade = "windows"
                    elif trade == "other" and any(k in combined_text for k in ("door", "flush", "panelled")):
                        trade = "doors"
                    elif trade == "other" and any(k in combined_text for k in ("vent", "pv")):
                        trade = "walls"
                    elif trade == "other" and any(k in combined_text for k in ("pillar", "column", "pier", "truss")):
                        trade = "structure"

                    if trade == "other" or not raw_tag or raw_tag.startswith("ITEM_") or raw_tag.isdigit():
                        continue
                    tag_name = normalized_opening.tag if normalized_opening else raw_tag
'''
text = require_replace(text, old_table, new_table, "table trade classification")

old_col = '''                is_window = any(k in col_text.lower() for k in ("casement", "window", "glass", "fixed glass"))
                is_door = any(k in col_text.lower() for k in ("door", "flush door", "panelled door"))

                if not (is_window or is_door):
                    continue

                trade = "windows" if is_window else "doors"
                dims = self._parse_dimensions_string(col_text)

                qty_match = re.search(r"\\b(\\d+)\\s*(?:no\\.?s?|nos?)\\b", col_text, re.I)
                qty = float(qty_match.group(1)) if qty_match else None

                c_x0 = min(w[0] for w in col_w)
                c_y0 = min(w[1] for w in col_w)
                c_x1 = max(w[2] for w in col_w)
                c_y1 = max(w[3] for w in col_w)

                tag_match = re.search(r"\\b(W\\d+|D\\d+)\\b", col_text, re.I)
                tag_name = tag_match.group(1).upper() if tag_match else f"{trade[0].upper()}_COL_{col_idx}"

                if qty is not None:
'''
new_col = '''                normalized_opening = normalize_opening_tag(col_text)
                is_window = any(k in col_text.lower() for k in ("casement", "window", "glass", "fixed glass"))
                is_door = any(k in col_text.lower() for k in ("door", "flush door", "panelled door"))

                if normalized_opening is not None:
                    trade = normalized_opening.trade_type
                elif is_window != is_door:
                    trade = "windows" if is_window else "doors"
                else:
                    continue

                dims = self._parse_dimensions_string(col_text)
                qty_match = re.search(r"\\b(\\d+)\\s*(?:no\\.?s?|nos?)\\b", col_text, re.I)
                qty = float(qty_match.group(1)) if qty_match else None

                c_x0 = min(w[0] for w in col_w)
                c_y0 = min(w[1] for w in col_w)
                c_x1 = max(w[2] for w in col_w)
                c_y1 = max(w[3] for w in col_w)

                tag_name = normalized_opening.tag if normalized_opening else f"{trade[0].upper()}_COL_{col_idx}"

                # Untagged visual columns remain provisional even when a count
                # is visible: type existence is not schedule identity.
                if qty is not None and normalized_opening is not None:
'''
text = require_replace(text, old_col, new_col, "column opening identity")
text = require_replace(
    text,
    'description=f"Column schedule item {tag_name} (unquantified)",',
    'description=f"Column schedule item {tag_name} (unresolved identity/count)",',
    "column provisional description",
)

dedup_anchor = '''        deduped: Dict[str, ScheduleRow] = {}
        vent_pages: Dict[int, float] = {}

        for r in rows:
'''
dedup_replacement = '''        deduped: Dict[str, ScheduleRow] = {}
        vent_pages: Dict[int, float] = {}

        # Canonical aliases for one documented opening identity must agree.
        # Conflicting counts or dimensions fail closed instead of allowing
        # source order / confidence to pick a winner.
        opening_groups: Dict[str, List[ScheduleRow]] = {}
        for candidate in rows:
            if candidate.is_provisional:
                continue
            norm = normalize_opening_tag(candidate.tag)
            if norm is None:
                continue
            candidate.tag = norm.tag
            candidate.trade_type = norm.trade_type
            opening_groups.setdefault(norm.tag, []).append(candidate)

        conflicting_opening_tags = set()
        for tag, group in opening_groups.items():
            quantities = {float(r.quantity) for r in group if r.quantity is not None}
            dimensions = {
                tuple(float(v) for v in r.dimensions[:2])
                for r in group
                if r.dimensions is not None and len(r.dimensions) >= 2
            }
            if len(quantities) > 1 or len(dimensions) > 1:
                conflicting_opening_tags.add(tag)

        for r in rows:
'''
text = require_replace(text, dedup_anchor, dedup_replacement, "dedup conflict prepass")
skip_anchor = '''            if r.is_provisional:
                continue

            if r.tag == "brick_vents":
'''
skip_replacement = '''            if r.is_provisional:
                continue

            norm = normalize_opening_tag(r.tag)
            if norm is not None:
                r.tag = norm.tag
                r.trade_type = norm.trade_type
                if r.tag in conflicting_opening_tags:
                    continue

            if r.tag == "brick_vents":
'''
text = require_replace(text, skip_anchor, skip_replacement, "dedup conflict skip")
raster.write_text(text, encoding="utf-8")

extractor = Path("pb_planreader_pdf_extractor.py")
text = extractor.read_text(encoding="utf-8")
start_marker = '''            # ------------------------------------------------------------------
            # 4 & 5. Window and Door Extraction with Evidence Binding (Phase F.12)
            # ------------------------------------------------------------------
'''
end_marker = '''            # Alternate explicit opening-tag conventions. Existing reconciled
'''
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("special-case opening section markers not found")
replacement = '''            # ------------------------------------------------------------------
            # 4 & 5. Window and Door Identity
            # ------------------------------------------------------------------
            # Opening identities are deliberately NOT inferred from dimensions.
            # Generic documented schedule/tag extraction is applied across the
            # whole drawing package by Phase F.8 after this page loop. The
            # contextual explicit-tag path below may add a count only when a
            # W/D identity is actually present in drawing text.

'''
text = text[:start] + replacement + text[end:]
extractor.write_text(text, encoding="utf-8")
