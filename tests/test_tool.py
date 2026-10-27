import unittest

import pandas as pd

from category_rules import CategoryRule, is_storage_product, apply_plus_size, base_rule, classify_product, infer_primary_category, infer_similar_category, rank_similar_categories
from csv_loader import load_csv_bytes, to_csv_bytes, variant_mask
from exporter import export_csv, verify_export
from format_adapter import SHOPIFY, prepare_frame
from pricing import apply_fixed_pricing, parse_number, validate_fixed_pricing
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
        boots = classify_product("Men's Waterproof Leather Work Boots")
        self.assertEqual(boots.rule_id, "Footwear::Boots")
        self.assertEqual((boots.minimum, boots.maximum), (39.00, 59.00))
        swimsuit = classify_product("Women's One Piece Swimsuit")
        self.assertEqual(swimsuit.rule_id, "Underwear, Sleepwear and Swimwear::One Piece Swimsuit")
        self.assertEqual((swimsuit.minimum, swimsuit.maximum), (20.00, 35.00))

    def test_womens_tie_dye_skate_shoes_stay_in_footwear(self):
        category = "Women's, Shoes, Skate Shoes"
        title = "womens-pastel-tie-dye-printed-platform-sneakers"
        self.assertEqual(infer_primary_category(category), "Footwear")
        category_rule = classify_product(category)
        self.assertIsNotNone(category_rule)
        self.assertEqual(category_rule.rule_id, "Footwear::Sneakers")
        title_rule = classify_product(title)
        self.assertIsNotNone(title_rule)
        self.assertEqual(title_rule.rule_id, "Footwear::Sneakers")
        source = pd.DataFrame([
            row("shoe-a", title, category, "20", "0", "SH-1", "https://example.com/shoe.jpg"),
            row("shoe-b", "womens-sage-green-printed-sneakers", category, "20", "0", "SH-2", "https://example.com/shoe2.jpg"),
        ])
        result = apply_fixed_pricing(source)
        self.assertEqual(result.product_summary["一级品类"].unique().tolist(), ["Footwear"])
        self.assertNotIn("Ties", result.product_summary["识别品类"].tolist())
        self.assertEqual(classify_product("Unisex Western Cowboy Boots").rule_id, "Footwear::Boots")
        self.assertEqual(infer_primary_category("Men's, Top, Vests"), "Men's Clothing")

    def test_sock_sets_are_socks_not_womens_clothing_sets(self):
        examples = (
            "Women's Cotton Socks Set",
            "Womens 5 Pack Crew Socks",
            "女士袜子套装",
            "Women's, Accessories, Socks",
        )
        for text in examples:
            with self.subTest(text=text):
                rule = classify_product(text)
                self.assertIsNotNone(rule)
                self.assertEqual(rule.rule_id, "Jewelry and Accessories::Socks")
                self.assertEqual((rule.minimum, rule.maximum), (9.99, 16.99))

    def test_watch_bands_have_their_own_price_range(self):
        for text in ("Apple Watch Band", "Smartwatch Strap", "手表表带"):
            with self.subTest(text=text):
                rule = classify_product(text)
                self.assertIsNotNone(rule)
                self.assertEqual(rule.rule_id, "Jewelry and Accessories::Watch Bands")
                self.assertEqual((rule.minimum, rule.maximum), (8.99, 18.99))
        self.assertEqual(classify_product("Women's Gold Watch").rule_id, "Jewelry and Accessories::Watches")

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

    def test_user_added_secondary_category_participates_in_pricing(self):
        source = pd.DataFrame([
            row("vest-a", "Men's Outdoor Utility Vest", "Men's, Tops, Vests", "20", "0", "V-1", "https://example.com/v.jpg"),
            row("vest-b", "Men's Lightweight Waistcoat", "Men's, Tops, Vests", "20", "0", "V-2", "https://example.com/v2.jpg"),
        ])
        custom_rule = CategoryRule(
            "Men's Clothing", "Vests", 32.99, 42.99, ("vest", "vests", "waistcoat")
        )
        result = apply_fixed_pricing(source, custom_category_rules=(custom_rule,))
        self.assertEqual(result.product_summary["识别品类"].unique().tolist(), ["Vests"])
        self.assertTrue(result.product_summary["新售价"].between(32.99, 42.99).all())
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


class RegressionTests(unittest.TestCase):
    """Cases found during code review of pricing accuracy."""

    def test_fashion_idioms_are_not_mistaken_for_other_products(self):
        expected = {
            "Women's Tie Front Dress": "Women's Clothing::Dresses",
            "Tie Waist Maxi Dress": "Women's Clothing::Dresses",
            "Women's Shelf Bra Tank Top": "Women's Clothing::Tops",
            "Women's Boot Cut Jeans": "Women's Clothing::Jeans",
            "Women's Short Sleeve Dress": "Women's Clothing::Dresses",
            "Women's Cap Sleeve Blouse": "Women's Clothing::Blouses",
            "Men's Dress Pants": "Men's Clothing::Pants",
            "Shoe Storage Rack": "Kitchen and Storage::Shoe Storage",
        }
        for title, rule_id in expected.items():
            with self.subTest(title=title):
                self.assertEqual(classify_product(title).rule_id, rule_id)

    def test_real_ties_boots_and_shorts_still_match(self):
        self.assertEqual(classify_product("Men's Silk Necktie").rule_id, "Jewelry and Accessories::Ties")
        self.assertEqual(classify_product("Men's Knit Tie").rule_id, "Jewelry and Accessories::Ties")
        self.assertEqual(classify_product("Women's Leather Boots").rule_id, "Footwear::Boots")
        self.assertEqual(classify_product("Men's Shorts").rule_id, "Men's Clothing::Shorts")
        self.assertEqual(classify_product("Tie Dye Sneakers").rule_id, "Footwear::Sneakers")

    def test_singular_nouns_match_their_category(self):
        self.assertEqual(classify_product("Women's Dress").rule_id, "Women's Clothing::Dresses")
        self.assertEqual(classify_product("Women's Hoodie").rule_id, "Women's Clothing::Hoodies")
        self.assertEqual(classify_product("Women's Cardigan").rule_id, "Women's Clothing::Cardigans")

    def test_plus_size_in_title_is_honoured_when_category_does_not_say_so(self):
        frame = pd.DataFrame([
            row("d1", "Women's Plus Size Floral Dress", "Women's Dresses", "10", "0", "D1", ""),
            row("d2", "Women's Floral Dress", "Women's Dresses", "10", "0", "D2", ""),
        ])
        summary = apply_fixed_pricing(frame).product_summary.set_index("Handle")
        self.assertEqual(summary.loc["d1", "识别品类"], "Dresses (Plus Size)")
        self.assertEqual(summary.loc["d1", "区间下限"], 36.99)
        self.assertEqual(summary.loc["d1", "区间上限"], 49.99)
        self.assertEqual(summary.loc["d2", "识别品类"], "Dresses")

    def test_plus_size_helpers_are_inverse_and_idempotent(self):
        base = classify_product("Women's Dresses")
        plus = apply_plus_size(base, "plus size")
        self.assertEqual(apply_plus_size(plus, "plus size"), plus)
        self.assertEqual(base_rule(plus), base)
        men = apply_plus_size(classify_product("Men's Hoodies"), "Plus-Size")
        self.assertEqual((men.minimum, men.maximum), (42.99, 52.99))
        self.assertEqual(base_rule(men), classify_product("Men's Hoodies"))

    def test_price_range_override_also_reaches_plus_size_products(self):
        frame = pd.DataFrame([row("d1", "Dress", "Women's Plus Size Dresses", "10", "0", "D1", "")])
        result = apply_fixed_pricing(
            frame,
            price_range_overrides={"Women's Clothing::Dresses": {"minimum": 50.0, "maximum": 60.0}},
        )
        record = result.product_summary.iloc[0]
        self.assertEqual((record["区间下限"], record["区间上限"]), (52.0, 65.0))
        self.assertTrue(52.0 <= record["新售价"] <= 65.0)

    def test_a_products_price_does_not_change_when_the_batch_grows(self):
        base = [row(f"p{i}", f"Women's Dress {i}", "Women's Dresses", "10", "0", f"S{i}", "") for i in range(30)]
        before = apply_fixed_pricing(pd.DataFrame(base)).product_summary.set_index("Handle")["新售价"]
        extra = base + [row("new", "Women's Dress new", "Women's Dresses", "10", "0", "SN", "")]
        after = apply_fixed_pricing(pd.DataFrame(extra)).product_summary.set_index("Handle")["新售价"]
        self.assertTrue((before == after[before.index]).all())

    def test_small_categories_still_get_distinct_prices(self):
        for count in (2, 3, 4, 5):
            frame = pd.DataFrame([
                row(f"s{i}", f"Women's Dress {i}", "Women's Dresses", "10", "0", f"S{i}", "") for i in range(count)
            ])
            summary = apply_fixed_pricing(frame).product_summary
            self.assertGreaterEqual(summary["新售价"].nunique(), min(4, count))

    def test_products_without_any_price_are_reported_not_silently_skipped(self):
        frame = pd.DataFrame([
            row("ok", "Women's Dress", "Women's Dresses", "10", "0", "A", ""),
            row("blank", "Women's Dress B", "Women's Dresses", "", "", "", ""),
        ])
        result = apply_fixed_pricing(frame)
        self.assertEqual(result.skipped_handles, ("blank",))

    def test_pricing_cache_returns_identical_but_independent_results(self):
        frame = pd.DataFrame([row("c1", "Women's Dress", "Women's Dresses", "10", "0", "C1", "")])
        first = apply_fixed_pricing(frame)
        second = apply_fixed_pricing(frame)
        pd.testing.assert_frame_equal(first.frame, second.frame)
        second.frame.loc[:, "price"] = "999"
        third = apply_fixed_pricing(frame)
        self.assertNotEqual(third.frame["price"].iloc[0], "999")
        changed = apply_fixed_pricing(frame, product_category_overrides={"c1": "Women's Clothing::Jackets"})
        self.assertEqual(changed.product_summary.iloc[0]["识别品类"], "Jackets")

    def test_parse_number_rejects_nan_and_inf(self):
        self.assertIsNone(parse_number("nan"))
        self.assertIsNone(parse_number("inf"))
        self.assertEqual(parse_number("$1,234.50"), 1234.5)


class StorageProductTests(unittest.TestCase):
    """A storage product is priced as storage, not as the thing it stores."""

    def test_storage_titles_are_classified_by_the_container(self):
        for title in ["Sock Storage Box", "Socks Organizer", "Bra Storage Box", "Tie Storage Box",
                      "Belt Rack", "Sunglasses Organizer", "Jewelry Box", "Underwear Storage Bag",
                      "袜子收纳箱", "内衣收纳盒"]:
            with self.subTest(title=title):
                self.assertEqual(classify_product(title).primary, "Kitchen and Storage")
        self.assertEqual(classify_product("Women's Sock Drawer Organizer").name, "Drawer Organizers")

    def test_real_clothing_and_furniture_are_not_affected(self):
        for title in ["Men's Cotton Socks", "Men's Silk Necktie", "Women's Tie Front Dress"]:
            with self.subTest(title=title):
                self.assertNotEqual(classify_product(title).primary if classify_product(title) else "", "Kitchen and Storage")
        self.assertFalse(is_storage_product("Storage Bed Frame"))
        self.assertFalse(is_storage_product("Storage Ottoman"))
        self.assertTrue(is_storage_product("Under Bed Storage Box"))

    def test_storage_product_filed_under_a_clothing_category_is_corrected_and_flagged(self):
        frame = pd.DataFrame([
            row("a", "Cotton Crew Socks 5 Pack", "Socks", "10", "0", "A", ""),
            row("b", "Foldable Sock Storage Box", "Socks", "10", "0", "B", ""),
            row("c", "Bamboo Socks", "Socks", "10", "0", "C", ""),
        ])
        summary = apply_fixed_pricing(frame).product_summary.set_index("Handle")
        self.assertEqual(summary.loc["a", "识别品类"], "Socks")
        self.assertEqual(summary.loc["c", "识别品类"], "Socks")
        self.assertEqual(summary.loc["b", "识别品类"], "Storage Boxes")
        self.assertIn("语义匹配", summary.loc["b", "匹配方式"])  # surfaces in the review step
        self.assertTrue(14.99 <= summary.loc["b", "新售价"] <= 39.99)

    def test_a_category_the_user_mapped_by_hand_is_not_second_guessed(self):
        frame = pd.DataFrame([
            row("b", "Foldable Sock Storage Box", "Socks", "10", "0", "B", ""),
            row("a", "Cotton Crew Socks", "Socks", "10", "0", "A", ""),
        ])
        result = apply_fixed_pricing(frame, category_overrides={"Socks": "Jewelry and Accessories::Socks"})
        self.assertEqual(set(result.product_summary["识别品类"]), {"Socks"})


class UnresolvedProductTests(unittest.TestCase):
    def test_unresolved_products_without_category_are_listed_and_can_be_fixed_per_product(self):
        frame = pd.DataFrame([
            row("ok1", "Women's Dress", "Women's Dresses", "10", "0", "A", ""),
            row("odd1", "Zzyzx Gizmo One", "", "12.50", "0", "B", ""),
            row("odd2", "Zzyzx Gizmo Two", "", "13.50", "0", "C", ""),
        ])
        result = apply_fixed_pricing(frame)
        self.assertEqual(set(result.unresolved_handles), {"odd1", "odd2"})
        details = {item["Handle"]: item for item in result.unresolved_details}
        self.assertEqual(details["odd1"]["原始分类"], "")
        self.assertEqual(details["odd1"]["商品名称"], "Zzyzx Gizmo One")
        self.assertEqual(details["odd1"]["原售价"], "12.50")
        self.assertEqual(details["odd1"]["SKU数量"], 1)

        fixed = apply_fixed_pricing(
            frame, product_category_overrides={"odd1": "Kitchen and Storage::Storage Boxes", "odd2": "Kitchen and Storage::Storage Boxes"}
        )
        self.assertEqual(fixed.unresolved_handles, ())
        self.assertEqual(fixed.unresolved_details, ())
        self.assertEqual(set(fixed.product_summary["Handle"]), {"ok1", "odd1", "odd2"})


SHOPIFY_SAMPLE = (
    "Handle,Title,Body (HTML),Type,Variant SKU,Variant Price,Variant Compare At Price,Image Src\n"
    'dress-a,Women\'s Dress A,"<p style=""color:red;"">Soft; warm; cozy</p>",Dresses,A1,19.99,,https://x.com/a.jpg\n'
    "dress-a,,,,A2,19.99,,\n"
    "dress-b,Women's Dress B,<p>Light</p>,Dresses,B1,19.99,,https://x.com/b.jpg\n"
    "dress-c,Women's Dress C,<p>Light</p>,Dresses,C1,19.99,,https://x.com/c.jpg\n"
).encode("utf-8")


class ExportVerificationTests(unittest.TestCase):
    def _run(self, data=SHOPIFY_SAMPLE):
        loaded = load_csv_bytes(data)
        source = prepare_frame(loaded.frame, SHOPIFY)
        result = apply_fixed_pricing(source)
        output = export_csv(result.frame, loaded, SHOPIFY)
        return data, loaded, result, output

    def test_verification_passes_for_a_correct_shopify_export(self):
        data, loaded, result, output = self._run()
        handles = tuple(result.product_summary["Handle"])
        self.assertEqual(verify_export(output, data, loaded, result.frame, SHOPIFY, handles), ())

    def test_shopify_empty_compare_price_stays_empty_when_not_discounted(self):
        data, loaded, result, output = self._run()
        reloaded = load_csv_bytes(output).frame
        undiscounted = result.frame["compare_at_price"].eq("0")
        self.assertTrue(undiscounted.any())
        self.assertTrue(reloaded.loc[undiscounted, "Variant Compare At Price"].eq("").all())
        discounted = ~undiscounted
        self.assertTrue(reloaded.loc[discounted, "Variant Compare At Price"].ne("").all())

    def test_verification_catches_a_modified_non_price_cell(self):
        data, loaded, result, output = self._run()
        tampered = output.replace(b"Light", b"Heavy", 1)
        issues = verify_export(tampered, data, loaded, result.frame, SHOPIFY, ())
        self.assertTrue(any("非价格单元格" in issue for issue in issues))

    def test_verification_catches_price_that_differs_from_plan(self):
        data, loaded, result, output = self._run()
        wrong = output.replace(b"dress-b,Women's Dress B,<p>Light</p>,Dresses,B1,", b"dress-b,Women's Dress B,<p>Light</p>,Dresses,B1,1", 1)
        issues = verify_export(wrong, data, loaded, result.frame, SHOPIFY, ())
        self.assertTrue(any("价格" in issue for issue in issues))

    def test_verification_catches_inconsistent_variant_prices(self):
        data, loaded, result, output = self._run()
        prices = result.product_summary.set_index("Handle")["新售价"]
        fixed = f"{prices['dress-a']:.2f}".encode()
        tampered = output.replace(b",A2," + fixed, b",A2,12.34", 1)
        issues = verify_export(tampered, data, loaded, result.frame, SHOPIFY, ("dress-a",))
        self.assertTrue(any("变体价格不一致" in issue for issue in issues))

    def test_semicolons_in_html_do_not_confuse_delimiter_detection(self):
        self.assertEqual(load_csv_bytes(SHOPIFY_SAMPLE).delimiter, ",")


if __name__ == "__main__":
    unittest.main()
