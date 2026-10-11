"""Read actual original raster detector dispositions; never publish source hosts."""
from __future__ import annotations

import ast
import argparse
from dataclasses import asdict
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
import re
import sys
import textwrap

import numpy as np

import pb_raster_visible_segment_detector as detector
from pb_migration_contracts import EvidenceResolutionStatus, stable_contract_id
from pb_physical_wall_candidate_authority import MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS
from pb_live_physical_net_wall_integration import LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION
from pb_source_visibility_authority import RASTER_RENDER_DPI, SourceVisibilityProducer


def _mask_digest(mask):
    return sha256(mask.tobytes(order="C")).hexdigest()


def _pixel_line(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in (int, float) for v in value)):
        raise ValueError("untyped original detector line receipt")
    try:
        line = tuple(float(v) for v in value)
    except (ValueError, OverflowError):
        raise ValueError("unmeasurable original detector line receipt") from None
    if not all(math.isfinite(v) for v in line):
        raise ValueError("nonfinite original detector line receipt")
    return line


def _dedupe_receipt(inputs, outputs):
    if not isinstance(inputs, (list, tuple)) or not isinstance(outputs, (list, tuple)):
        raise ValueError("unknown original dedupe inventory structure")
    if len(inputs) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
        raise ValueError("over-limit original dedupe inventory")
    before = [_pixel_line(line) for line in inputs]
    after = [_pixel_line(line) for line in outputs]
    groups = {}
    for index, line in enumerate(before):
        key = tuple(round(v, 3) for v in line)
        groups.setdefault(key, []).append(index)
    if sorted(groups) != after:
        raise ValueError("original dedupe output/parent receipt disagreement")
    return {"input_lines_px": [list(x) for x in before], "output_lines_px": [list(x) for x in after],
        "groups": [{"output_line_px": list(line), "input_indices": groups[line],
            "coalescence_observed": len(groups[line]) > 1,
            "rounding_observed": any(before[i] != line for i in groups[line]),
            "physical_equivalence_proven": False} for line in after]}


def _snap_trace_anchors(function):
    source, first_line = inspect.getsourcelines(function)
    source = textwrap.dedent("".join(source))
    tree = ast.parse(source)
    anchors = {}
    tests = {"right - left > 0.0": "horizontal_first", "bottom - top > 0.0": "vertical"}
    for node in ast.walk(tree):
        role = tests.get(ast.unparse(node.test)) if isinstance(node, ast.If) else None
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) == "final_h.append"):
            role = "horizontal_second"
        if role:
            if role in anchors.values():
                raise ValueError("ambiguous original snap loop structure")
            anchors[first_line+node.lineno-1] = role
    if set(anchors.values()) != {"horizontal_first", "vertical", "horizontal_second"}:
        raise ValueError("unknown original snap loop structure")
    return anchors, sha256(source.encode()).hexdigest()


def _length_trace_anchor(function):
    source, first_line = inspect.getsourcelines(function)
    source = textwrap.dedent("".join(source))
    expected = "math.hypot(geometry_pt[2] - geometry_pt[0], geometry_pt[3] - geometry_pt[1]) < _MIN_LINE_LENGTH_PT"
    anchors = [first_line+n.lineno-1 for n in ast.walk(ast.parse(source))
               if isinstance(n, ast.If) and ast.unparse(n.test) == expected]
    if len(anchors) != 1:
        raise ValueError("unknown original detector minimum-length structure")
    return anchors[0], sha256(source.encode()).hexdigest()


class _Observer:
    def __init__(self):
        self.foreground = None
        self.foreground_pixels = None
        self.foreground_code = detector._foreground_mask.__code__
        self.component_code = detector._component_segments.__code__
        self.dedupe_code = detector._dedupe.__code__
        self.snap_code = detector._snap_intersections.__code__
        self.detector_code = detector.detect_axis_aligned_raster_segments.__code__
        self.length_line, self.detector_code_sha256 = _length_trace_anchor(detector.detect_axis_aligned_raster_segments)
        self.length_rows = []
        self.length_seen = set()
        self.snap_lines, self.snap_code_sha256 = _snap_trace_anchors(detector._snap_intersections)
        self.snap_steps = []
        self.snap_inputs = None
        self.snap_outputs = None
        self.dedupes = []
        self.components = []
        self.component_pixels = {}
        self.component_returns = {}
        self.failed_frames = set()

    def _components(self, frame, returned):
        local = frame.f_locals
        if not {"mask", "orientation", "min_line_px", "stats", "_labels"} <= local.keys():
            raise ValueError("unknown original component receipt structure")
        orientation = local["orientation"]
        minimum = local["min_line_px"]
        if orientation not in ("horizontal", "vertical") or type(minimum) is not int or minimum <= 0:
            raise ValueError("invalid original component orientation or minimum")
        if orientation in self.component_returns:
            raise ValueError("duplicate original component mask call")
        output = [tuple(line) for line in returned]
        mask = local["mask"]
        labels = local["_labels"]
        mask_sha = _mask_digest(mask)
        stats = local["stats"]
        if len(stats)-1+len(self.components) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
            raise ValueError("over-limit original component observational inventory")
        emitted = []
        for index, stat in enumerate(stats[1:], start=1):
            x, y, width, height, area = (int(v) for v in stat)
            bitmap = labels[y:y+height, x:x+width] == index
            if int(np.count_nonzero(bitmap)) != area:
                raise ValueError("original component pixel/stat receipt contradiction")
            along, cross = (width, height) if orientation == "horizontal" else (height, width)
            reasons = []
            if area <= 0:
                reasons.append("nonpositive_component_area")
            if along < minimum:
                reasons.append("component_along_length_below_existing_minimum")
            if along < max(3, 3*cross):
                reasons.append("component_aspect_below_existing_minimum")
            expected = ((float(x), y+(height-1)/2., float(x+width-1), y+(height-1)/2.)
                        if orientation == "horizontal" else
                        (x+(width-1)/2., float(y), x+(width-1)/2., float(y+height-1)))
            actual = [line for line in output if line == expected]
            if bool(actual) != (not reasons):
                raise ValueError("original component filter/output receipt disagreement")
            line = actual[0] if actual else None  # Exact equal geometry; no owner election.
            if line is not None:
                emitted.append(line)
            bbox = [x, y, x+width-1, y+height-1]
            pixel_sha = _mask_digest(bitmap)
            cid = stable_contract_id("raster_detector_component", {"orientation": orientation,
                "mask_shape": list(mask.shape), "bbox": bbox, "pixel_sha256": pixel_sha})
            if cid in self.component_pixels:
                raise ValueError("duplicate original component pixel address")
            ys, xs = np.nonzero(bitmap)
            self.component_pixels[cid] = (xs+x, ys+y)
            self.components.append({"component_id": cid, "orientation": orientation,
                "pixel_bbox": bbox, "foreground_area_px": area,
                "original_mask_sha256": mask_sha, "component_pixel_sha256": pixel_sha,
                "component_pixel_encoding": "row-major bool of original connected-component label in its bbox",
                "pixels_also_in_original_foreground": int(np.count_nonzero(
                    self.foreground_pixels[ys+y,xs+x])) if self.foreground_pixels is not None else 0,
                "minimum_line_px": minimum, "existing_rejection_reasons": reasons,
                "original_component_line_px": list(line) if line is not None else None,
                "source_ownership_proven": False, "host_publication_allowed": False})
        if sorted(emitted) != sorted(output):
            raise ValueError("original component output lacks complete pixel ancestry")
        self.component_returns[orientation] = output

    def __call__(self, frame, event, arg):
        if frame.f_code not in (self.foreground_code, self.component_code, self.dedupe_code,
                               self.snap_code, self.detector_code):
            return None
        if event == "exception":
            self.failed_frames.add(id(frame))
        if event == "return" and id(frame) in self.failed_frames:
            self.failed_frames.remove(id(frame))
            return self
        if frame.f_code is self.component_code and event == "return":
            self._components(frame, arg)
        if frame.f_code is self.dedupe_code and event == "return":
            if "segments" not in frame.f_locals:
                raise ValueError("unknown original dedupe receipt structure")
            self.dedupes.append(_dedupe_receipt(frame.f_locals["segments"], arg))
        if frame.f_code is self.snap_code:
            local = frame.f_locals
            if event == "call":
                if self.snap_inputs is not None:
                    raise ValueError("duplicate original snap call")
                tolerance = local["tolerance_px"]
                if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance <= 0:
                    raise ValueError("invalid original snap tolerance receipt")
                self.snap_inputs = {"horizontal": [list(_pixel_line(x)) for x in local["horizontal"]],
                    "vertical": [list(_pixel_line(x)) for x in local["vertical"]], "tolerance_px": tolerance}
            if event == "line" and frame.f_lineno in self.snap_lines:
                role = self.snap_lines[frame.f_lineno]
                if role == "vertical":
                    before = (local["x0"], local["y0"], local["_x1"], local["y1"])
                    after = (local["x0"], local["top"], local["x0"], local["bottom"])
                    positive = local["bottom"]-local["top"] > 0.0
                else:
                    before = (local["x0"], local["y0"], local["x1"], local["_y1"])
                    after = (local["left"], local["y0"], local["right"], local["y0"])
                    positive = local["right"]-local["left"] > 0.0
                self.snap_steps.append({"original_pass": role,
                    "input_line_px": list(_pixel_line(before)), "output_line_px": list(_pixel_line(after)),
                    "positive_span_observed": positive,
                    "kept_in_original_pass": role == "horizontal_second" or positive,
                    "host_contact_proven": False})
            if event == "return":
                self.snap_outputs = {"horizontal": [list(_pixel_line(x)) for x in arg[0]],
                                     "vertical": [list(_pixel_line(x)) for x in arg[1]]}
        if frame.f_code is self.detector_code and event == "line" and frame.f_lineno == self.length_line:
            local = frame.f_locals
            address = (local["orientation"], _pixel_line(local["segment"]))
            # CPython can revisit a multi-line condition's first line while
            # evaluating its arguments. Post-dedupe lines are unique per axis.
            if address in self.length_seen:
                return self
            self.length_seen.add(address)
            geometry = _pixel_line(local["geometry_pt"])
            length = math.hypot(geometry[2]-geometry[0], geometry[3]-geometry[1])
            if not math.isfinite(length):
                raise ValueError("nonfinite original detector post-snap length")
            minimum = frame.f_globals["_MIN_LINE_LENGTH_PT"]
            self.length_rows.append({"orientation": local["orientation"],
                "input_post_snap_line_px": list(_pixel_line(local["segment"])),
                "original_geometry_pt": list(geometry), "original_length_pt": length,
                "original_minimum_length_pt": minimum, "minimum_length_rejected": length < minimum,
                "source_primitive_ref": None, "host_publication_allowed": False})
        if frame.f_code is self.foreground_code and event == "return" and "gray" in frame.f_locals:
            gray = frame.f_locals["gray"]
            polarities = []
            for name in ("dark", "light"):
                mask = frame.f_locals.get(name)
                if mask is not None:
                    area = int(np.count_nonzero(mask))
                    fraction = area / mask.size
                    polarities.append({"polarity": name, "foreground_area_px": area,
                        "foreground_fraction": fraction, "mask_sha256": _mask_digest(mask),
                        "passes_existing_foreground_fraction":
                        detector._MIN_FOREGROUND_FRACTION <= fraction <= detector._MAX_FOREGROUND_FRACTION})
            selected = [p["polarity"] for p in polarities
                        if arg is not None and p["mask_sha256"] == _mask_digest(arg)]
            if arg is not None and len(selected) != 1:
                raise ValueError("original foreground polarity receipt ambiguous")
            self.foreground = {"image_shape_px": list(gray.shape), "gray_sha256": _mask_digest(gray),
                "original_polarity_receipts": polarities, "selected_polarity": selected[0] if selected else None,
                "foreground_area_px": int(np.count_nonzero(arg)) if arg is not None else None,
                "foreground_mask_sha256": _mask_digest(arg) if arg is not None else None}
            self.foreground_pixels = arg.copy() if arg is not None else None
        return self


def _validate_snap_capture(observer):
    if observer.snap_inputs is None:
        if observer.snap_steps or observer.dedupes:
            raise ValueError("partial original snap receipt inventory")
        return
    if len(observer.dedupes) != 4 or observer.snap_outputs is None:
        raise ValueError("incomplete original snap/dedupe receipts")
    steps = {role: [r for r in observer.snap_steps if r["original_pass"] == role]
             for role in ("horizontal_first", "vertical", "horizontal_second")}
    first_h = steps["horizontal_first"]
    first_v = steps["vertical"]
    second_h = steps["horizontal_second"]
    checks = [
        (observer.dedupes[0]["output_lines_px"], observer.snap_inputs["horizontal"]),
        (observer.dedupes[1]["output_lines_px"], observer.snap_inputs["vertical"]),
        ([r["input_line_px"] for r in first_h], observer.snap_inputs["horizontal"]),
        ([r["input_line_px"] for r in first_v], observer.snap_inputs["vertical"]),
        ([r["output_line_px"] for r in first_h if r["kept_in_original_pass"]],
         [r["input_line_px"] for r in second_h]),
        ([r["output_line_px"] for r in second_h], observer.dedupes[2]["input_lines_px"]),
        ([r["output_line_px"] for r in first_v if r["kept_in_original_pass"]], observer.dedupes[3]["input_lines_px"]),
        (observer.dedupes[2]["output_lines_px"], observer.snap_outputs["horizontal"]),
        (observer.dedupes[3]["output_lines_px"], observer.snap_outputs["vertical"]),
    ]
    if any(a != b for a,b in checks):
        raise ValueError("original snap transformation receipt disagreement")


def observe_original_snap_passes(horizontal, vertical, *, tolerance_px):
    """Observe the unchanged snap function for synthetic verification, not source authority."""
    if sys.gettrace() is not None:
        raise ValueError("existing Python trace prevents isolated detector observation")
    observer = _Observer()
    try:
        sys.settrace(observer)
        observed = detector._snap_intersections(detector._dedupe(horizontal), detector._dedupe(vertical),
                                                tolerance_px=tolerance_px)
    finally:
        sys.settrace(None)
    baseline = detector._snap_intersections(detector._dedupe(horizontal), detector._dedupe(vertical),
                                            tolerance_px=tolerance_px)
    if observed != baseline:
        raise ValueError("original snap observation changed output")
    _validate_snap_capture(observer)
    return {"original_snap_inputs": observer.snap_inputs, "original_snap_outputs": observer.snap_outputs,
        "original_snap_pass_receipts": observer.snap_steps, "original_dedupe_calls": observer.dedupes,
        "source_scope_authenticated": False, "host_publication_allowed": False}


def _dedupe_parent_lists(call, parents):
    if len(parents) != len(call["input_lines_px"]):
        raise ValueError("original dedupe parent index inventory incomplete")
    result = []
    for group in call["groups"]:
        group_parents = set()
        for index in group["input_indices"]:
            if not parents[index]:
                raise ValueError("original dedupe input lacks pixel component ancestry")
            group_parents.update(parents[index])
        group["component_parent_ids"] = sorted(group_parents)
        result.append(group_parents)
    return result


def _annotate_dispositions(observer, observed):
    if observer.snap_inputs is None:
        if observer.length_rows or observer.components:
            raise ValueError("partial original detector component/length capture")
        return
    first_parents = {}
    for index, orientation in enumerate(("horizontal", "vertical")):
        rows = [r for r in observer.components if r["orientation"] == orientation
                and r["original_component_line_px"] is not None]
        if [r["original_component_line_px"] for r in rows] != observer.dedupes[index]["input_lines_px"]:
            raise ValueError("original component/dedupe order receipt disagreement")
        first_parents[orientation] = _dedupe_parent_lists(observer.dedupes[index],
                                                         [{r["component_id"]} for r in rows])
    steps = {role: [r for r in observer.snap_steps if r["original_pass"] == role]
             for role in ("horizontal_first", "vertical", "horizontal_second")}
    kept = {}
    for role, parents in (("horizontal_first", first_parents["horizontal"]),
                          ("vertical", first_parents["vertical"])):
        if len(steps[role]) != len(parents):
            raise ValueError("original snap parent index inventory incomplete")
        for row, ids in zip(steps[role], parents):
            row["component_parent_ids"] = sorted(ids)
        kept[role] = [set(r["component_parent_ids"]) for r in steps[role] if r["kept_in_original_pass"]]
    if len(steps["horizontal_second"]) != len(kept["horizontal_first"]):
        raise ValueError("original second-pass horizontal ancestry incomplete")
    for row, ids in zip(steps["horizontal_second"], kept["horizontal_first"]):
        row["component_parent_ids"] = sorted(ids)
    final_parents = {
        "horizontal": _dedupe_parent_lists(observer.dedupes[2],
                             [set(r["component_parent_ids"]) for r in steps["horizontal_second"]]),
        "vertical": _dedupe_parent_lists(observer.dedupes[3], kept["vertical"]),
    }
    expected = [(orientation, line, parents) for orientation in ("horizontal", "vertical")
                for line, parents in zip(observer.snap_outputs[orientation], final_parents[orientation])]
    if len(expected) != len(observer.length_rows):
        raise ValueError("incomplete original detector minimum-length receipts")
    matched = set()
    for row, (orientation, line, parents) in zip(observer.length_rows, expected):
        if row["orientation"] != orientation or row["input_post_snap_line_px"] != line:
            raise ValueError("original post-snap detector line order disagreement")
        row["component_parent_ids"] = sorted(parents)
        indices = [i for i,s in enumerate(observed) if s.orientation == orientation
                   and list(s.pixel_geometry) == line and list(s.geometry_pt) == row["original_geometry_pt"]]
        if len(indices) != (0 if row["minimum_length_rejected"] else 1):
            raise ValueError("original minimum-length/final-output receipt disagreement")
        row["final_detector_output_index"] = indices[0] if indices else None
        matched.update(indices)
    if matched != set(range(len(observed))):
        raise ValueError("final original detector output lacks complete pixel ancestry")
    for component in observer.components:
        cid = component["component_id"]
        component["final_detector_output_indices"] = sorted(r["final_detector_output_index"]
            for r in observer.length_rows if cid in r["component_parent_ids"] and not r["minimum_length_rejected"])
        losses = ["original_component_filter"] if component["existing_rejection_reasons"] else []
        losses += ["original_snap_"+r["original_pass"]+"_nonpositive_span" for r in observer.snap_steps
                   if cid in r["component_parent_ids"] and not r["kept_in_original_pass"]]
        if any(cid in r["component_parent_ids"] and r["minimum_length_rejected"] for r in observer.length_rows):
            losses.append("original_post_snap_minimum_length")
        component["observed_loss_stages"] = sorted(set(losses))
        component["dedupe_coalescence_observed"] = any(g["coalescence_observed"] and cid in g["component_parent_ids"]
            for call in observer.dedupes for g in call["groups"])
        component["snap_endpoint_change_observed"] = any(cid in r["component_parent_ids"]
            and r["input_line_px"] != r["output_line_px"] for r in observer.snap_steps)
        if not component["final_detector_output_indices"] and not losses:
            raise ValueError("original component disappeared without an observed disposition")


def _positive_pixel_runs(xs, ys, foreground, *, orientation):
    """Keep complete contiguous mask runs also present in original foreground."""
    if orientation not in ("horizontal", "vertical"):
        raise ValueError("unknown original pixel-run orientation")
    if (not isinstance(xs,np.ndarray) or not isinstance(ys,np.ndarray) or xs.ndim != 1 or ys.ndim != 1
            or xs.shape != ys.shape or xs.dtype.kind not in "iu" or ys.dtype.kind not in "iu"):
        raise ValueError("untyped original pixel-run coordinate inventory")
    if foreground is None:
        return []
    if not isinstance(foreground,np.ndarray) or foreground.ndim != 2 or foreground.dtype != np.uint8:
        raise ValueError("invalid original pixel-run foreground frame")
    if (np.any(xs < 0) or np.any(ys < 0) or np.any(xs >= foreground.shape[1])
            or np.any(ys >= foreground.shape[0])):
        raise ValueError("original pixel-run coordinates outside foreground frame")
    if len(np.unique(np.stack((xs,ys),axis=1),axis=0)) != len(xs):
        raise ValueError("duplicate original pixel-run coordinate")
    supported = foreground[ys,xs] != 0
    fixed, along = (ys[supported],xs[supported]) if orientation == "horizontal" else (xs[supported],ys[supported])
    result = []
    for coordinate in np.unique(fixed):
        positions = np.sort(along[fixed == coordinate])
        groups = np.split(positions,np.nonzero(np.diff(positions) != 1)[0]+1)
        for group in groups:
            result.append((int(coordinate),int(group[0]),int(group[-1])))
    return result


def _query_receipts(observer, queries):
    if not isinstance(queries, (list, tuple)) or len(queries) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
        raise ValueError("invalid or over-limit original pixel query inventory")
    if queries and observer.foreground is None:
        raise ValueError("pixel query has no decoded original render frame")
    seen = set()
    result = []
    total_run_receipts = 0
    scale = RASTER_RENDER_DPI/72.
    for query in queries:
        if not isinstance(query, dict) or set(query) != {"query_id", "render_bbox_pt"}:
            raise ValueError("invalid original pixel query structure")
        qid = query["query_id"]
        if not isinstance(qid, str) or not qid.strip() or qid != qid.strip() or qid in seen:
            raise ValueError("invalid or duplicate original pixel query address")
        seen.add(qid)
        x0,y0,x1,y1 = _pixel_line(query["render_bbox_pt"])
        height,width = observer.foreground["image_shape_px"]
        if min(x0,y0) < 0 or x1 < x0 or y1 < y0 or x1 > width/scale or y1 > height/scale:
            raise ValueError("original pixel query outside render frame")
        intersections = []
        for component in observer.components:
            bx0,by0,bx1,by1 = (v/scale for v in component["pixel_bbox"])
            if min(x1,bx1) < max(x0,bx0) or min(y1,by1) < max(y0,by0):
                continue
            xs,ys = observer.component_pixels[component["component_id"]]
            inside = (xs/scale >= x0) & (xs/scale <= x1) & (ys/scale >= y0) & (ys/scale <= y1)
            actual_x,actual_y = xs[inside],ys[inside]
            count = len(actual_x)
            original_foreground_count = (int(np.count_nonzero(observer.foreground_pixels[actual_y,actual_x]))
                                         if observer.foreground_pixels is not None else 0)
            runs = []
            for fixed,lo,hi in _positive_pixel_runs(xs,ys,observer.foreground_pixels,orientation=component["orientation"]):
                line = ([lo,fixed,hi,fixed] if component["orientation"] == "horizontal" else [fixed,lo,fixed,hi])
                rx0,ry0,rx1,ry1 = [v/scale for v in line]
                if min(rx1,x1) < max(rx0,x0) or min(ry1,y1) < max(ry0,y0):
                    continue
                total_run_receipts += 1
                if total_run_receipts > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
                    raise ValueError("over-limit original positive-pixel run receipt inventory")
                runs.append({"orientation":component["orientation"],"complete_run_pixel_geometry":line,
                    "complete_run_render_geometry_pt":[v/scale for v in line],"contiguous_pixel_count":hi-lo+1,
                    "component_pixels_and_original_foreground_all_positive":True,
                    "query_did_not_trim_endpoints":True,"source_primitive_ref":None,
                    "physical_wall_line_proven":False,"host_publication_allowed":False})
            intersections.append({"component_id": component["component_id"],
                "orientation": component["orientation"], "component_pixel_bbox": component["pixel_bbox"],
                "component_pixel_sha256": component["component_pixel_sha256"],
                "bbox_intersection_observed": True, "actual_component_pixels_in_query": count,
                "query_pixels_also_in_original_foreground": original_foreground_count,
                "original_positive_pixel_run_receipts": runs,
                "actual_pixel_center_bbox": [int(actual_x.min()),int(actual_y.min()),int(actual_x.max()),int(actual_y.max())]
                    if count else None,
                "existing_rejection_reasons": component["existing_rejection_reasons"],
                "observed_loss_stages": component["observed_loss_stages"],
                "final_detector_output_indices": component["final_detector_output_indices"],
                "source_ownership_proven": False, "host_publication_allowed": False})
        result.append({"query_id": qid, "render_bbox_pt": [x0,y0,x1,y1],
            "pixel_coordinate_rule": "inclusive original mask pixel centers; point conversion uses render DPI",
            "bbox_intersecting_components": sorted(intersections,key=lambda r:(r["orientation"],r["component_pixel_bbox"],r["component_id"])),
            "opening_or_wall_ownership_authenticated": False, "host_publication_allowed": False})
    return sorted(result,key=lambda r:r["query_id"])


def observe_detector_dispositions(png_bytes: bytes, *, queries=()) -> dict:
    if not isinstance(png_bytes, (bytes, bytearray, memoryview)):
        raise TypeError("png_bytes must be bytes-like")
    if sys.gettrace() is not None:
        raise ValueError("existing Python trace prevents isolated detector observation")
    observer = _Observer()
    try:
        sys.settrace(observer)
        observed = detector.detect_axis_aligned_raster_segments(png_bytes, dpi=RASTER_RENDER_DPI)
    finally:
        sys.settrace(None)
    baseline = detector.detect_axis_aligned_raster_segments(png_bytes, dpi=RASTER_RENDER_DPI)
    if baseline != observed:
        raise ValueError("original detector disposition observation changed output")
    if len(observed) > MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS:
        raise ValueError("over-limit original detector observational inventory")
    _validate_snap_capture(observer)
    _annotate_dispositions(observer, observed)
    query_rows = _query_receipts(observer, queries)
    failure = ("raster_png_decode_unavailable" if observer.foreground is None else
               "original_foreground_mask_unavailable" if observer.foreground["selected_polarity"] is None else None)
    return {"render_sha256": sha256(png_bytes).hexdigest(), "render_dpi": RASTER_RENDER_DPI,
        "detector_version": detector.RASTER_VISIBLE_SEGMENT_DETECTOR_VERSION,
        "foreground": observer.foreground, "first_observed_failure": failure,
        "component_receipts": sorted(observer.components, key=lambda r:(r["orientation"], r["pixel_bbox"], r["component_id"])),
        "original_dedupe_calls": observer.dedupes,
        "original_snap_inputs": observer.snap_inputs, "original_snap_outputs": observer.snap_outputs,
        "original_snap_pass_receipts": observer.snap_steps,
        "original_snap_function_sha256": observer.snap_code_sha256,
        "original_detector_function_sha256": observer.detector_code_sha256,
        "original_post_snap_length_receipts": observer.length_rows,
        "pixel_query_receipts": query_rows,
        "observed_original_segment_count": len(observed), "original_detector_output_unchanged": True,
        "primitive_safety_cap": MAX_WALL_TOPOLOGY_SOURCE_SEGMENTS,
        "evidence_resolution_status": EvidenceResolutionStatus.ABSTAINED.value,
        "visibility_publication_proven": False, "post_detection_region_coverage_not_audited": True,
        "source_universe_completeness_proven": False, "physical_equivalence_proven": False,
        "host_publication_allowed": False, "opening_count_publication_allowed": False,
        "metric_quantity_publication_allowed": False, "benchmark_accuracy": None}


def original_source_detector_dispositions(source_bytes: bytes, *, page_id: str,
        expected_source_sha: str, expected_render_sha: str | None = None, queries=()) -> dict:
    if not isinstance(source_bytes, bytes):
        raise TypeError("original source PDF must be bytes")
    if (not isinstance(expected_source_sha,str) or not re.fullmatch(r"[0-9a-f]{64}",expected_source_sha)
            or sha256(source_bytes).hexdigest() != expected_source_sha):
        raise ValueError("original detector source PDF SHA mismatch")
    if (not isinstance(page_id,str) or not page_id.isascii() or not page_id.isdigit()
            or int(page_id) < 1 or str(int(page_id)) != page_id):
        raise ValueError("invalid canonical original source page")
    if expected_render_sha is not None and (not isinstance(expected_render_sha,str)
            or not re.fullmatch(r"[0-9a-f]{64}",expected_render_sha)):
        raise ValueError("invalid original render SHA")
    producer = SourceVisibilityProducer(producer_method="live-physical-net-wall",
        producer_version=LIVE_PHYSICAL_NET_WALL_INTEGRATION_SCHEMA_VERSION)
    published = producer.ingest_native_pdf_bytes(document_id=f"live-source:{expected_source_sha[:32]}",
        source_bytes=source_bytes, source_locator="memory://live-physical-net-wall-source.pdf", page_ids=(page_id,))
    scope = {"document_id": published.revision.document_id, "revision_id": published.revision.revision_id,
        "source_sha256": expected_source_sha, "snapshot_id": published.snapshot.snapshot_id,
        "page_id": page_id, "dpi": float(RASTER_RENDER_DPI), "include_native_frame": True}
    png, parent, frame = producer._producer.render_native_page_png(**scope)
    render_sha = sha256(png).hexdigest()
    if expected_render_sha is not None and render_sha != expected_render_sha:
        raise ValueError("original detector render SHA mismatch")
    result = observe_detector_dispositions(png, queries=queries)
    replay, replay_parent, replay_frame = producer._producer.render_native_page_png(**scope)
    if replay != png or replay_parent != parent or replay_frame != frame:
        raise ValueError("immutable original render replay changed")
    result.update(source_sha256=expected_source_sha, document_id=published.revision.document_id,
        revision_id=published.revision.revision_id, snapshot_id=published.snapshot.snapshot_id,
        page_id=page_id, viewport_id=None, native_page_parent_observation_id=parent.observation_id,
        native_page_frame=asdict(frame), original_source_render_reauthenticated=True,
        query_coordinate_space="display render pixel centers divided by render pixels per point")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf",type=Path,required=True)
    parser.add_argument("--page-id",required=True)
    parser.add_argument("--expected-source-sha",required=True)
    parser.add_argument("--expected-render-sha")
    parser.add_argument("--queries-json",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    queries = json.loads(args.queries_json.read_text()) if args.queries_json else ()
    result = original_source_detector_dispositions(args.pdf.read_bytes(),page_id=args.page_id,
        expected_source_sha=args.expected_source_sha, expected_render_sha=args.expected_render_sha, queries=queries)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print(json.dumps({"source_sha256":result["source_sha256"],"render_sha256":result["render_sha256"],
        "observed_original_segment_count":result["observed_original_segment_count"],
        "component_receipts":len(result["component_receipts"]),
        "original_detector_output_unchanged":result["original_detector_output_unchanged"]}))


if __name__ == "__main__":
    main()
