# -*- coding: utf-8 -*-
__title__ = 'AutoJoin'
__author__ = 'Matej'

from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView

# 1. Warning handler to prevent Revit from cancelling the transaction
class WarningSwallower(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        failures = failuresAccessor.GetFailureMessages()
        for f in failures:
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(f)
        return DB.FailureProcessingResult.Continue

# 2. Expanded category list (Structural and Architectural)
allowed_builtincats = [
    DB.BuiltInCategory.OST_Walls,
    DB.BuiltInCategory.OST_Floors,
    DB.BuiltInCategory.OST_Ceilings,
    DB.BuiltInCategory.OST_Stairs,
    DB.BuiltInCategory.OST_Columns,
    DB.BuiltInCategory.OST_StructuralColumns,
    DB.BuiltInCategory.OST_StructuralFoundation,
    DB.BuiltInCategory.OST_StructuralFraming,
    DB.BuiltInCategory.OST_Roofs
]

struct_builtincats = [
    DB.BuiltInCategory.OST_StructuralColumns,
    DB.BuiltInCategory.OST_StructuralFoundation,
    DB.BuiltInCategory.OST_StructuralFraming
]

allowed_cat_ids = [DB.Category.GetCategory(doc, c).Id.Value for c in allowed_builtincats if DB.Category.GetCategory(doc, c)]
struct_cat_ids = [DB.Category.GetCategory(doc, c).Id.Value for c in struct_builtincats if DB.Category.GetCategory(doc, c)]

# 3. Intelligent Selection Logic (Selection vs Active View)
selection_ids = uidoc.Selection.GetElementIds()
if selection_ids:
    raw_elements = [doc.GetElement(eid) for eid in selection_ids]
    mode_text = "Selection"
else:
    raw_elements = DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType().ToElements()
    mode_text = "Active View"

# Filter raw elements by categories and exclude groups
categories_dict = {}
valid_elements = []
for el in raw_elements:
    if hasattr(el, "GroupId") and el.GroupId.Value == -1: # Exclude groups
        cat = el.Category
        if cat and cat.Id.Value in allowed_cat_ids:
            categories_dict[cat.Name] = cat
            valid_elements.append(el)

if not categories_dict:
    forms.alert("No valid elements found in current {}. Check your selection and categories.".format(mode_text), exitscript=True)

# 4. English UI with Slovak warning
selected_cat_names = forms.SelectFromList.show(
    sorted(categories_dict.keys()),
    title="AutoJoin ({})\n\n⚠️ Upozornenie: pred spustením skontroluj nastavenie priority prvkov!".format(mode_text),
    button_name="Join Selected",
    multiselect=True
)

if not selected_cat_names:
    forms.alert("No categories selected. Operation cancelled.", exitscript=True)

# 5. Prepare elements based on UI selection
selected_category_values = [categories_dict[name].Id.Value for name in selected_cat_names]
elements_to_join = [e for e in valid_elements if e.Category.Id.Value in selected_category_values]

joined_count = 0
failed_count = 0
switched_count = 0
processed_pairs = set()

# 6. Execution with Progress Bar
with forms.ProgressBar(title="Joining elements from {}...".format(mode_text), cancellable=True) as pb:
    total_elements = len(elements_to_join)
    
    t = DB.Transaction(doc, "AutoJoin ({}): ".format(mode_text) + ", ".join(selected_cat_names))
    t.Start()
    
    options = t.GetFailureHandlingOptions()
    options.SetFailuresPreprocessor(WarningSwallower())
    t.SetFailureHandlingOptions(options)
    
    for index, el1 in enumerate(elements_to_join):
        if pb.cancelled:
            break
            
        pb.update_progress(index, total_elements)
        
        bbox1 = el1.get_BoundingBox(None)
        if not bbox1:
            continue
            
        # Tolerance expansion to catch touching faces
        tolerance = 0.16 
        outline = DB.Outline(
            DB.XYZ(bbox1.Min.X - tolerance, bbox1.Min.Y - tolerance, bbox1.Min.Z - tolerance),
            DB.XYZ(bbox1.Max.X + tolerance, bbox1.Max.Y + tolerance, bbox1.Max.Z + tolerance)
        )
        bb_filter = DB.BoundingBoxIntersectsFilter(outline)
        
        # Collect candidates
        if mode_text == "Active View":
            touching_candidates = DB.FilteredElementCollector(doc, view.Id).WherePasses(bb_filter).ToElements()
        else:
            touching_candidates = [e for e in valid_elements if bb_filter.PassesFilter(e)]
            
        touching_ids = [e.Id.Value for e in touching_candidates]
        
        for el2 in elements_to_join:
            if el1.Id.Value == el2.Id.Value:
                continue
            
            pair_id = tuple(sorted([el1.Id.Value, el2.Id.Value]))
            if pair_id in processed_pairs:
                continue
            
            if el2.Id.Value in touching_ids:
                processed_pairs.add(pair_id)
                
                # 1. Join Geometry
                if not DB.JoinGeometryUtils.AreElementsJoined(doc, el1, el2):
                    try:
                        DB.JoinGeometryUtils.JoinGeometry(doc, el1, el2)
                        joined_count += 1
                    except Exception:
                        failed_count += 1
                        continue

                # 2. Switch Join Order (Structural Priority)
                if DB.JoinGeometryUtils.AreElementsJoined(doc, el1, el2):
                    is_el1_struct = el1.Category.Id.Value in struct_cat_ids
                    is_el2_struct = el2.Category.Id.Value in struct_cat_ids
                    
                    try:
                        if is_el1_struct and not is_el2_struct:
                            if DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, el2, el1):
                                DB.JoinGeometryUtils.SwitchJoinOrder(doc, el1, el2)
                                switched_count += 1
                        elif is_el2_struct and not is_el1_struct:
                            if DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, el1, el2):
                                DB.JoinGeometryUtils.SwitchJoinOrder(doc, el1, el2)
                                switched_count += 1
                    except Exception:
                        pass

    t.Commit()

print("AutoJoin Finished (Source: {})".format(mode_text))
print("Successfully joined: {}.".format(joined_count))
print("Join order prioritized (Structural): {}.".format(switched_count))
if failed_count > 0:
    print("Failed/Skipped: {}.".format(failed_count))