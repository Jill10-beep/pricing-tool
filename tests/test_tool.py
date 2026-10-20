import unittest

import pandas as pd

from category_rules import classify_product, infer_primary_category, infer_similar_category, rank_similar_categories
from csv_loader import load_csv_bytes, to_csv_bytes, variant_mask
from exporter import export_csv
from format_adapter import SHOPIFY, prepare_frame
from pricing import apply_fixed_pricing, validate_fixed_pricing
from validator import validate_frame


def row(handle, title, category, price, compare, sku, image):
    return {
        "Handle": handle,
        "Title": title,
        "category": category,
        "price": price,
        "compare_at_price": compare,
        "sku_code": sku,
        "inventory_quantity": "100",
        "Image Src": image,
    }


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            row("shirt-a", "Men's Classic Shirt", "Men's Shirts", "88", "199", "A-RED", "https://example.com/a.jpg"),
            row("shirt-a", "", "", "77", "0", "A-BLUE", "https://example.com/b.jpg"),
            row("shirt-a", "", "", "", "", "", "https://example.com/c.jpg"),
            row("shirt-b", "Men's Oxford Shirt", "Men's Shirts", "9", "0", "B-1", "https://example.com/d.jpg"),
            row("shirt-c", "Men's Linen Shirt", "Men's Shirts", "9", "0", "C-1", "https://example.com/e.jpg"),
            row("chair-a", "Modern Dining Chair", "Furniture", "20", "0", "F-1", "https://example.com/f.jpg"),
        ]
    )


class ToolTests(unittest.TestCase):
    def test_csv_round_trip_preserves_rows_and_columns(self):
        source = sample_frame()
        loaded = load_csv_bytes(to_csv_bytes(source))
        self.assertEqual(loaded.frame.shape, source.shape)
        self.assertEqual(loaded.frame.columns.tolist(), source.columns.tolist())

    def test_export_preserves_original_bom_state(self):
        plain = b'Handle,Title,category,price,compare_at_price,sku_code,inventory_quantity,Image Src\nitem,Men\'s Shirt,Men\'s Shirts,10,0,S1,2,https://example.com/a.jpg\n'
        loaded_plain = load_csv_bytes(plain)
        result_plain = apply_fixed_pricing(loaded_plain.frame)
        self.assertFalse(export_csv(result_plain.frame, loaded_plain).startswith(b"\xef\xbb\xbf"))

        bom = b"\xef\xbb\xbf" + plain
        loaded_bom = load_csv_bytes(bom)
        result_bom = apply_fixed_pricing(loaded_bom.frame)
        self.assertTrue(export_csv(result_bom.frame, loaded_bom).startswith(b"\xef\xbb\xbf"))

    def test_category_mapping(self):
        self.assertEqual(classify_product("Men's Polo Shirt").rule_id, "Men's Clothing::Polo Shirts")
        self.assertEqual(classify_product("Modern furniture chair").rule_id, "Home Decor and Bedding::Furniture")
        self.assertEqual(classify_product("Men's Necktie").rule_id, "Jewelry and Accessories::Ties")
        inferred, method = infer_similar_category("Men's Necktie")
        self.assertEqual(inferred.name, "Ties")
        self.assertTrue(method.startswith("层级匹配"))
        underwear, underwear_method = infer_similar_category("Men's Cotton Boxer Briefs")
        self.assertEqual(underwear.rule_id, "Men's Clothing::Underwear")
        self.assertTrue(underwear_method.startswith("层级匹配"))
        bra = classify_product("Women's Lace Wireless Bra")
        self.assertEqual(bra.rule_id, "Underwear, Sleepwear and Swimwear::Bras")
        self.assertEqual((bra.minimum, bra.maximum), (19.99, 29.99))
        cardigan = classify_product("Women's, Tops, Cardigans")
        self.assertEqual(cardigan.rule_id, "Women's Clothing::Cardigans")
        self.assertEqual((cardigan.minimum, cardigan.maximum), (34.99, 44.99))

    def test_gender_words_never_cross_match(self):
        women = classify_product("womens botanical panties Women's, Underwear, Panties")
        self.assertEqual(women.rule_id, "Underwear, Sleepwear and Swimwear::Panties (Multipacks)")
        self.assertNotEqual(women.primary, "Men's Clothing")
        self.assertEqual(classify_product("Women's cotton T-Shirt").primary, "Women's Clothing")
        self.assertEqual(classify_product("Men's cotton T-Shirt").primary, "Men's Clothing")
        self.assertEqual(classify_product("Men's Waterproof Leather Work Boots").rule_id, "Footwear::Boots")
        self.assertEqual(classify_product("Unisex Western Cowboy Boots").rule_id, "Footwear::Boots")
        self.assertEqual(infer_primary_category("Men's, Top, Vests"), "Men's Clothing")

    def test_local_similarity_returns_candidates_and_is_conservative(self):
        candidates = rank_similar_categories("electric coffee grinder", 3)
        self.assertEqual(candidates[0][0].rule_id, "Kitchen and Storage::Kitchen Tools")
        inferred, method = infer_similar_category("electric coffee grinder")
        self.assertEqual(inferred.rule_id, "Kitchen and Storage::Kitchen Tools")
        self.assertIn("语义匹配", method)
        uncertain, _ = infer_similar_category("portable espresso maker")
        self.assertIsNone(uncertain)

    def test_description_styling_words_cannot_override_product_category(self):
        source = pd.DataFrame([{
            **row("dress-a", "Linen Blend Day Dress", "Women's, Dresses, Casual Dresses", "20", "0", "D-1", "https://example.com/dress.jpg"),
            "tags": "summer floral",
            "body_html": "Complete the look by pairing this dress with leather boots.",
        }])
        result = apply_fixed_pricing(source)
        self.assertEqual(result.unresolved_handles, ())
        self.assertEqual(result.product_summary.iloc[0]["一级品类"], "Women's Clothing")
        self.assertEqual(result.product_summary.iloc[0]["识别品类"], "Dresses")
        self.assertIn("原始分类", result.product_summary.iloc[0]["匹配方式"])

    def test_learned_category_override(self):
        source = pd.DataFrame([
            row("mystery-a", "Unlisted Product", "New Supplier Type", "10", "0", "M-1", "https://example.com/m.jpg")
        ])
        unresolved = apply_fixed_pricing(source)
        self.assertEqual(len(unresolved.unresolved_handles), 1)
        learned = apply_fixed_pricing(source, {"New Supplier Type": "Jewelry and Accessories::Belts"})
        self.assertEqual(len(learned.unresolved_handles), 0)
        self.assertEqual(learned.product_summary.iloc[0]["一级品类"], "Jewelry and Accessories")
        self.assertEqual(learned.product_summary.iloc[0]["识别品类"], "Belts")

    def test_unresolved_product_stays_unchanged_and_does_not_block_export(self):
        source = pd.DataFrame([
            row("shirt-a", "Men's Classic Shirt", "Men's Shirts", "88", "199", "S-1", "https://example.com/s.jpg"),
            row("unknown-b", "Completely Unlisted Object", "Unknown Supplier Category", "123.45", "234.56", "U-1", "https://example.com/u.jpg"),
        ])
        result = apply_fixed_pricing(source)
        self.assertEqual(result.unresolved_handles, ("unknown-b",))
        self.assertEqual(len(result.product_summary), 1)
        unchanged = result.frame[result.frame["Handle"] == "unknown-b"].iloc[0]
        self.assertEqual(unchanged["price"], "123.45")
        self.assertEqual(unchanged["compare_at_price"], "234.56")
        self.assertEqual(validate_fixed_pricing(result), ())

    def test_manual_mapping_overrides_automatic_conflict_check(self):
        source = pd.DataFrame([
            row(
                "ambiguous-hoodie",
                "Men's Highland Cow Printed Hoodie",
                "Unlisted Hooded Tops",
                "20",
                "0",
                "H-1",
                "https://example.com/h.jpg",
            )
        ])
        confirmed = apply_fixed_pricing(
            source,
            {"Unlisted Hooded Tops": "Women's Clothing::Hoodies"},
        )
        self.assertEqual(confirmed.unresolved_handles, ())
        self.assertEqual(confirmed.expected_products, 1)
        self.assertEqual(len(confirmed.product_summary), 1)
        self.assertEqual(confirmed.product_summary.iloc[0]["识别品类"], "Hoodies")
        self.assertEqual(validate_fixed_pricing(confirmed), ())

    def test_same_supplier_category_cannot_split_into_different_categories(self):
        source = pd.DataFrame([
            row("a", "Men's Classic Shirt", "Supplier Collection A", "20", "0", "A", "https://example.com/a.jpg"),
            row("b", "Men's Oxford Shirt", "Supplier Collection A", "20", "0", "B", "https://example.com/b.jpg"),
            row("c", "Men's Linen Shirt", "Supplier Collection A", "20", "0", "C", "https://example.com/c.jpg"),
            row("d", "Men's Casual Shirt", "Supplier Collection A", "20", "0", "D", "https://example.com/d.jpg"),
            row("e", "Outdoor Leather Boots", "Supplier Collection A", "20", "0", "E", "https://example.com/e.jpg"),
        ])
        result = apply_fixed_pricing(source)
        self.assertEqual(result.unresolved_handles, ())
        self.assertEqual(len(result.product_summary), 5)
        self.assertEqual(result.product_summary["识别品类"].nunique(), 1)
        self.assertEqual(result.product_summary.iloc[0]["识别品类"], "Shirts")
        self.assertTrue(result.product_summary["匹配方式"].str.contains("同一原始分类多数一致").all())

    def test_single_product_override_only_changes_selected_product_category(self):
        source = pd.DataFrame([
            row("top-a", "Women's Knit Top", "Women's, Tops", "20", "0", "A", "https://example.com/a.jpg"),
            row("cardigan-b", "Women's Wool Cardigan", "Women's, Tops", "20", "0", "B", "https://example.com/b.jpg"),
        ])
        result = apply_fixed_pricing(
            source,
            product_category_overrides={"cardigan-b": "Women's Clothing::Sweaters"},
        )
        categories = dict(zip(result.product_summary["Handle"], result.product_summary["识别品类"]))
        methods = dict(zip(result.product_summary["Handle"], result.product_summary["匹配方式"]))
        self.assertEqual(categories["top-a"], "Tops")
        self.assertEqual(categories["cardigan-b"], "Sweaters")
        self.assertIn("单个商品人工纠正", methods["cardigan-b"])

    def test_multiple_product_overrides_apply_in_one_run(self):
        source = pd.DataFrame([
            row("top-a", "Women's Knit Top", "Women's, Tops", "20", "0", "A", "https://example.com/a.jpg"),
            row("wrong-b", "Women's Layered Top", "Women's, Tops", "20", "0", "B", "https://example.com/b.jpg"),
            row("wrong-c", "Women's Button Top", "Women's, Tops", "20", "0", "C", "https://example.com/c.jpg"),
        ])
        result = apply_fixed_pricing(
            source,
            product_category_overrides={
                "wrong-b": "Women's Clothing::Cardigans",
                "wrong-c": "Women's Clothing::Cardigans",
            },
        )
        categories = dict(zip(result.product_summary["Handle"], result.product_summary["识别品类"]))
        self.assertEqual(categories["top-a"], "Tops")
        self.assertEqual(categories["wrong-b"], "Cardigans")
        self.assertEqual(categories["wrong-c"], "Cardigans")

    def test_same_product_variants_have_same_price(self):
        result = apply_fixed_pricing(sample_frame())
        priced = result.frame[result.frame["Handle"] == "shirt-a"]
        variants = priced[variant_mask(priced)]
        self.assertEqual(variants["price"].nunique(), 1)
        self.assertEqual(variants["compare_at_price"].nunique(), 1)
        self.assertEqual(priced.iloc[2]["price"], "")

    def test_blank_handles_group_by_title_rows(self):
        source = sample_frame().copy()
        source["Handle"] = ""
        result = apply_fixed_pricing(source)
        self.assertEqual(len(result.product_summary), 4)
        first_product = result.frame.iloc[:3]
        variants = first_product[variant_mask(first_product)]
        self.assertEqual(variants["price"].nunique(), 1)

    def test_missing_skus_fall_back_to_price_rows(self):
        source = sample_frame().copy()
        source["sku_code"] = ""
        self.assertEqual(int(variant_mask(source).sum()), 5)
        result = apply_fixed_pricing(source)
        self.assertEqual(len(result.product_summary), 4)

    def test_mixed_sku_file_prices_every_price_bearing_product(self):
        source = pd.DataFrame([
            row("skirt-a", "Women's Midi Skirt", "Women's, Bottoms, Skirts", "25.99", "0", "S-1", "https://example.com/a.jpg"),
            row("skirt-a", "", "", "25.99", "0", "", "https://example.com/a2.jpg"),
            row("pants-b", "Women's Wide Leg Pants", "Women's, Bottoms, Pants", "25.99", "0", "", "https://example.com/b.jpg"),
        ])
        self.assertEqual(int(variant_mask(source).sum()), 3)
        result = apply_fixed_pricing(source)
        self.assertEqual(result.expected_products, 2)
        self.assertEqual(len(result.product_summary), 2)
        self.assertEqual(validate_fixed_pricing(result), ())
        self.assertTrue(result.frame["price"].astype(str).str.strip().ne("25.99").all())

    def test_prices_are_in_fixed_ranges_and_vary_within_category(self):
        result = apply_fixed_pricing(sample_frame())
        shirts = result.product_summary[result.product_summary["识别品类"] == "Shirts"]
        self.assertTrue(shirts["新售价"].between(29.99, 39.99).all())
        self.assertGreater(shirts["新售价"].nunique(), 1)
        furniture = result.product_summary[result.product_summary["识别品类"] == "Furniture"]
        self.assertTrue(furniture["新售价"].between(79.90, 99.90).all())

    def test_custom_price_range_is_used_without_changing_category(self):
        source = pd.DataFrame([
            row("chair-a", "Modern Dining Chair", "Furniture", "20", "0", "F-1", "https://example.com/f.jpg"),
            row("chair-b", "Modern Accent Chair", "Furniture", "20", "0", "F-2", "https://example.com/f2.jpg"),
        ])
        custom = {"Home Decor and Bedding::Furniture": {"minimum": 109.90, "maximum": 139.99}}
        result = apply_fixed_pricing(source, price_range_overrides=custom)
        self.assertEqual(result.product_summary["识别品类"].unique().tolist(), ["Furniture"])
        self.assertTrue(result.product_summary["新售价"].between(109.90, 139.99).all())
        self.assertTrue(result.product_summary["新划线价"].replace(0, 109.90).between(109.90, 139.99).all())
        self.assertEqual(validate_fixed_pricing(result), ())

    def test_discount_is_by_product_and_within_range(self):
        result = apply_fixed_pricing(sample_frame())
        discounted = result.product_summary[result.product_summary["新划线价"] > 0]
        self.assertEqual(len(discounted), 2)
        self.assertTrue(discounted["折扣率"].between(10, 20).all())
        self.assertTrue((discounted["新划线价"] <= discounted["区间上限"]).all())
        self.assertEqual(validate_fixed_pricing(result), ())

    def test_export_only_changes_price_cells(self):
        raw = b'Handle,Title,category,price,compare_at_price,sku_code,inventory_quantity,Image Src\r\nshirt-a,"Men\'s, Shirt",Men\'s Shirts,"88",199,A-1,100,https://example.com/a.jpg\r\n'
        loaded = load_csv_bytes(raw)
        result = apply_fixed_pricing(loaded.frame)
        exported = export_csv(result.frame, loaded)
        before = raw.decode("utf-8")
        after = exported.decode("utf-8")
        self.assertIn('shirt-a,"Men\'s, Shirt",Men\'s Shirts,', after)
        self.assertTrue(after.endswith("\r\n"))
        self.assertNotEqual(before, after)

    def test_shopify_adapter_and_export_preserve_shopify_schema(self):
        raw = (
            b'Handle,Title,Product Category,Type,Variant SKU,Variant Price,Variant Compare At Price,Image Src\r\n'
            b'dress-a,Floral Midi Dress,Apparel & Accessories > Clothing > Dresses,Dresses,D-1,88,0,https://example.com/a.jpg\r\n'
        )
        loaded = load_csv_bytes(raw)
        canonical = prepare_frame(loaded.frame, SHOPIFY)
        result = apply_fixed_pricing(canonical)
        exported = export_csv(result.frame, loaded, SHOPIFY)
        exported_text = exported.decode("utf-8")
        self.assertTrue(exported_text.startswith("Handle,Title,Product Category,Type,Variant SKU,Variant Price,Variant Compare At Price,Image Src"))
        self.assertEqual(len(load_csv_bytes(exported).frame.columns), 8)
        self.assertIn("D-1", exported_text)
        self.assertNotIn(",88,0,", exported_text)

    def test_validation_understands_image_only_row(self):
        summary = validate_frame(sample_frame())
        self.assertEqual(summary.products, 4)
        self.assertEqual(summary.variants, 5)
        self.assertEqual(summary.image_only_rows, 1)


if __name__ == "__main__":
    unittest.main()
