from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CategoryRule:
    primary: str
    name: str
    minimum: float
    maximum: float
    keywords: tuple[str, ...]

    @property
    def rule_id(self) -> str:
        return f"{self.primary}::{self.name}"


# primary|subcategory|min|max. This is the user's complete English price table.
_TABLE = """
Women's Clothing|Dresses|34.99|44.99
Women's Clothing|Tops|22.99|29.99
Women's Clothing|T-Shirts|19.99|24.99
Women's Clothing|Shirts|24.99|32.99
Women's Clothing|Blouses|24.99|34.99
Women's Clothing|Sweaters|34.99|44.99
Women's Clothing|Hoodies|34.99|44.99
Women's Clothing|Sweatshirts|34.99|44.99
Women's Clothing|Jeans|34.99|44.99
Women's Clothing|Pants|32.99|44.99
Women's Clothing|Leggings|19.99|29.99
Women's Clothing|Shorts|22.99|29.99
Women's Clothing|Skirts|24.99|34.99
Women's Clothing|Jumpsuits|39.99|49.99
Women's Clothing|Rompers|34.99|44.99
Women's Clothing|Jackets|49.99|69.99
Women's Clothing|Coats|59.99|79.99
Women's Clothing|Blazers|39.99|49.99
Women's Clothing|Activewear|29.99|44.99
Women's Clothing|Loungewear|24.99|34.99
Women's Clothing|Sets|39.99|49.99
Women's Clothing|Shapewear Pants|24.99|34.99
Men's Clothing|T-Shirts|22.99|29.99
Men's Clothing|Shirts|29.99|39.99
Men's Clothing|Polo Shirts|29.99|39.99
Men's Clothing|Hoodies|39.99|49.99
Men's Clothing|Sweaters|39.99|49.99
Men's Clothing|Jeans|39.99|49.99
Men's Clothing|Pants|34.99|44.99
Men's Clothing|Shorts|24.99|34.99
Men's Clothing|Jackets|49.99|69.99
Men's Clothing|Coats|59.99|89.99
Men's Clothing|Suits|79.99|129.99
Men's Clothing|Activewear|34.99|49.99
Men's Clothing|Loungewear|29.99|39.99
Men's Clothing|Underwear|12.99|19.99
Footwear|Sneakers|49.99|69.99
Footwear|Casual Shoes|39.99|49.99
Footwear|Sandals|29.99|39.99
Footwear|Slippers|19.99|29.99
Footwear|Boots|49.99|69.99
Footwear|Heels|39.99|49.99
Footwear|Flats|29.99|39.99
Footwear|Loafers|39.99|49.99
Footwear|Running Shoes|49.99|69.99
Footwear|Outdoor Shoes|49.99|79.99
Bags|Handbags|34.99|49.99
Bags|Shoulder Bags|29.99|44.99
Bags|Crossbody Bags|24.99|39.99
Bags|Tote Bags|24.99|39.99
Bags|Backpacks|39.99|59.99
Bags|Wallets|14.99|24.99
Bags|Clutches|19.99|34.99
Bags|Travel Bags|39.99|69.99
Bags|Cosmetic Bags|12.99|19.99
Jewelry and Accessories|Necklaces|9.99|19.99
Jewelry and Accessories|Earrings|6.99|16.99
Jewelry and Accessories|Rings|8.99|16.99
Jewelry and Accessories|Bracelets|8.99|18.99
Jewelry and Accessories|Jewelry Sets|14.99|24.99
Jewelry and Accessories|Anklets|6.99|12.99
Jewelry and Accessories|Brooches|8.99|16.99
Jewelry and Accessories|Watches|29.99|59.99
Jewelry and Accessories|Sunglasses|14.99|24.99
Jewelry and Accessories|Hats|14.99|24.99
Jewelry and Accessories|Caps|14.99|24.99
Jewelry and Accessories|Belts|14.99|24.99
Jewelry and Accessories|Gloves|14.99|24.99
Jewelry and Accessories|Scarves|14.99|29.99
Jewelry and Accessories|Socks|9.99|16.99
Jewelry and Accessories|Ties|14.99|24.99
Jewelry and Accessories|Hair Accessories|6.99|14.99
Jewelry and Accessories|Bras|19.99|29.99
Underwear, Sleepwear and Swimwear|Panties (Multipacks)|12.99|19.99
Underwear, Sleepwear and Swimwear|Lingerie Sets|24.99|39.99
Underwear, Sleepwear and Swimwear|Bodysuits|24.99|34.99
Underwear, Sleepwear and Swimwear|Pajamas|24.99|34.99
Underwear, Sleepwear and Swimwear|Nightwear|19.99|29.99
Underwear, Sleepwear and Swimwear|Robes|29.99|44.99
Underwear, Sleepwear and Swimwear|Shapewear|24.99|39.99
Underwear, Sleepwear and Swimwear|Bikini|24.99|34.99
Underwear, Sleepwear and Swimwear|One Piece Swimsuit|29.99|39.99
Underwear, Sleepwear and Swimwear|Swim Cover Ups|24.99|34.99
Underwear, Sleepwear and Swimwear|Beachwear|24.99|39.99
Sports and Outdoor|Yoga Wear|29.99|44.99
Sports and Outdoor|Fitness Wear|29.99|44.99
Sports and Outdoor|Running Gear|29.99|49.99
Sports and Outdoor|Cycling|39.99|69.99
Sports and Outdoor|Camping|29.99|99.99
Sports and Outdoor|Hiking|39.99|89.99
Beauty|Makeup|9.99|24.99
Beauty|Skincare|12.99|39.99
Beauty|Hair Care|12.99|29.99
Beauty|Nail Care|6.99|19.99
Beauty|Beauty Tools|9.99|29.99
Beauty|Fragrance|24.99|59.99
Beauty|Bath & Body|9.99|24.99
Home Decor and Bedding|Wall Decor|19.99|49.99
Home Decor and Bedding|Lighting|29.99|79.99
Home Decor and Bedding|Mirrors|29.99|69.99
Home Decor and Bedding|Rugs|29.99|89.99
Home Decor and Bedding|Curtains|24.99|59.99
Home Decor and Bedding|Furniture|79.90|99.90
Home Decor and Bedding|Garden Decor|19.99|69.99
Home Decor and Bedding|Bedding Sets|49.99|99.99
Home Decor and Bedding|Pillows|24.99|49.99
Home Decor and Bedding|Blankets|29.99|59.99
Home Decor and Bedding|Quilts|39.99|89.99
Home Decor and Bedding|Mattress Covers|24.99|49.99
Home Decor and Bedding|Towels|14.99|39.99
Kitchen and Storage|Cookware|29.99|99.99
Kitchen and Storage|Bakeware|14.99|39.99
Kitchen and Storage|Kitchen Tools|9.99|29.99
Kitchen and Storage|Kitchen Storage|14.99|39.99
Kitchen and Storage|Food Containers|9.99|29.99
Kitchen and Storage|Cups & Mugs|12.99|24.99
Kitchen and Storage|Bottles|14.99|29.99
Kitchen and Storage|Tableware|19.99|59.99
Kitchen and Storage|Storage Boxes|14.99|39.99
Kitchen and Storage|Closet Storage|14.99|39.99
Kitchen and Storage|Drawer Organizers|9.99|29.99
Kitchen and Storage|Shoe Storage|19.99|49.99
Kitchen and Storage|Travel Organizers|12.99|34.99
Pet and Electronics|Pet Toys|9.99|24.99
Pet and Electronics|Pet Beds|29.99|79.99
Pet and Electronics|Pet Feeding|14.99|39.99
Pet and Electronics|Pet Grooming|12.99|39.99
Pet and Electronics|Pet Clothing|14.99|29.99
Pet and Electronics|Phone Accessories|12.99|39.99
Pet and Electronics|Chargers|14.99|39.99
Pet and Electronics|Earphones|24.99|79.99
Pet and Electronics|Smart Devices|39.99|149.99
Pet and Electronics|Computer Accessories|19.99|79.99
Holidays, Gifts and POD|Christmas|9.99|49.99
Holidays, Gifts and POD|Halloween|9.99|49.99
Holidays, Gifts and POD|Valentine's Day|9.99|59.99
Holidays, Gifts and POD|Birthday|9.99|59.99
Holidays, Gifts and POD|Gift Packaging|2.99|6.99
Holidays, Gifts and POD|Print on Demand T-Shirts|29.99|39.99
Holidays, Gifts and POD|Print on Demand Hoodies|39.99|54.99
Holidays, Gifts and POD|Print on Demand Mugs|19.99|29.99
Holidays, Gifts and POD|Print on Demand Posters|19.99|39.99
Holidays, Gifts and POD|Print on Demand Canvas|39.99|89.99
Holidays, Gifts and POD|Print on Demand Tote Bags|24.99|34.99
Holidays, Gifts and POD|Print on Demand Phone Cases|19.99|29.99
Holidays, Gifts and POD|Print on Demand Hats|24.99|34.99
Tools and Home Improvement|Screwdriver Set|12.99|29.99
Tools and Home Improvement|Wrench Set|15.99|39.99
Tools and Home Improvement|Hex Key Set|9.99|24.99
Tools and Home Improvement|Pliers Set|12.99|29.99
Tools and Home Improvement|Measuring Tape|8.99|19.99
Tools and Home Improvement|Tool Bag|15.99|39.99
Tools and Home Improvement|Hand Tool Set|25.99|59.99
Tools and Home Improvement|Home Repair Tool Kit|29.99|69.99
Automotive, Outdoor and Office|Car Phone Holder|14.99|29.99
Automotive, Outdoor and Office|Car Seat Organizer|15.99|29.99
Automotive, Outdoor and Office|Car Sun Shade|15.99|34.99
Automotive, Outdoor and Office|Car Cleaning Kit|12.99|29.99
Automotive, Outdoor and Office|Car Floor Mats|25.99|59.99
Automotive, Outdoor and Office|Trunk Organizer|25.99|49.99
Automotive, Outdoor and Office|Car Emergency Kit|29.99|69.99
Automotive, Outdoor and Office|Car Interior Accessories|19.99|49.99
Automotive, Outdoor and Office|Outdoor Tools|15.99|49.99
Automotive, Outdoor and Office|Camping Gear|19.99|59.99
Automotive, Outdoor and Office|Outdoor Storage|15.99|39.99
Automotive, Outdoor and Office|Office Supplies|9.99|29.99
Automotive, Outdoor and Office|Desk Organizer|12.99|29.99
Automotive, Outdoor and Office|Stationery Supplies|7.99|24.99
""".strip()


ALIASES: dict[str, tuple[str, ...]] = {
    "Women's Clothing::Sets": ("women's, sets", "women's set", "womens set", "women tracksuit", "jogger set", "two piece set", "女套装", "女运动套装"),
    "Men's Clothing::Underwear": ("boxer brief", "boxer briefs", "men underwear", "men's underwear", "briefs", "trunks", "男士内裤"),
    "Jewelry and Accessories::Ties": ("necktie", "neckties", "neck tie", "knit tie", "bow tie", "tie", "ties", "领带", "领结"),
    "Home Decor and Bedding::Furniture": ("furniture", "chair", "sofa", "cabinet", "shelf", "家具", "椅子", "沙发"),
    "Men's Clothing::Shirts": ("men shirt", "men's shirt", "mens shirt", "男衬衫"),
    "Men's Clothing::Polo Shirts": ("men polo", "men's polo", "mens polo", "polo shirt", "男polo"),
    "Women's Clothing::T-Shirts": ("women t-shirt", "women's t-shirt", "womens t-shirt", "女t恤"),
    "Men's Clothing::T-Shirts": ("men t-shirt", "men's t-shirt", "mens t-shirt", "男t恤"),
    "Beauty::Skincare": ("skin care", "serum", "moisturizer", "cleanser", "face mask", "护肤"),
    "Beauty::Makeup": ("lipstick", "mascara", "eyeshadow", "foundation", "彩妆"),
    "Footwear::Running Shoes": ("running shoe", "跑鞋"),
    "Footwear::Casual Shoes": ("casual shoe", "休闲鞋"),
}


def _default_keywords(name: str) -> tuple[str, ...]:
    parts = [name.lower()]
    parts.extend(part.strip().lower() for part in name.split("/") if part.strip())
    parts.extend(part[:-1] for part in list(parts) if part.endswith("s") and len(part) > 4)
    return tuple(dict.fromkeys(parts))


def _build_rules() -> tuple[CategoryRule, ...]:
    result = []
    for line in _TABLE.splitlines():
        primary, name, low, high = line.split("|")
        rule_id = f"{primary}::{name}"
        keywords = tuple(dict.fromkeys((*ALIASES.get(rule_id, ()), *_default_keywords(name))))
        result.append(CategoryRule(primary, name, float(low), float(high), keywords))
    return tuple(result)


CATEGORY_RULES = _build_rules()
PRIMARY_CATEGORIES = tuple(dict.fromkeys(rule.primary for rule in CATEGORY_RULES))

PRIMARY_KEYWORDS = {
    "Women's Clothing": ("women's", "womens", "women ", "female", "女士", "女装", "女式"),
    "Men's Clothing": ("men's", "mens", "men ", "male", "男士", "男装", "男式"),
    "Footwear": ("footwear", "shoe", "shoes", "鞋", "靴"),
    "Bags": ("bags", "bag", "backpack", "wallet", "包", "钱包"),
    "Jewelry and Accessories": ("jewelry", "accessories", "accessory", "necklace", "earring", "necktie", "tie", "belt", "首饰", "配饰", "领带"),
    "Underwear, Sleepwear and Swimwear": ("lingerie", "sleepwear", "swimwear", "pajama", "bikini", "内衣", "睡衣", "泳装"),
    "Sports and Outdoor": ("sports", "yoga", "fitness", "cycling", "hiking", "运动户外"),
    "Beauty": ("beauty", "makeup", "skincare", "cosmetic", "美容", "美妆", "护肤"),
    "Home Decor and Bedding": ("home decor", "bedding", "furniture", "家具", "家居", "床品"),
    "Kitchen and Storage": ("kitchen", "cookware", "厨房", "收纳"),
    "Pet and Electronics": ("pet", "electronics", "electronic", "宠物", "电子"),
    "Holidays, Gifts and POD": ("holiday", "gift", "pod", "print on demand", "节日", "礼品"),
    "Tools and Home Improvement": ("tools", "tool", "home improvement", "工具", "维修"),
    "Automotive, Outdoor and Office": ("automotive", "car ", "office", "汽车", "办公"),
}


def _normalize(text: str) -> str:
    return " ".join(str(text).lower().replace("_", " ").replace("-", " ").split())


def _contains(text: str, keyword: str) -> bool:
    keyword = _normalize(keyword)
    if re.search(r"[\u4e00-\u9fff]", keyword):
        return keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def rules_for_primary(primary: str) -> tuple[CategoryRule, ...]:
    return tuple(rule for rule in CATEGORY_RULES if rule.primary == primary)


def infer_primary_category(text: str) -> str | None:
    normalized = _normalize(text)
    scores = {primary: sum(_contains(normalized, k) for k in words) for primary, words in PRIMARY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


def _apply_plus_size(rule: CategoryRule, text: str) -> CategoryRule:
    if not (_contains(text, "plus size") or "大码" in text):
        return rule
    if rule.primary == "Women's Clothing":
        return CategoryRule(rule.primary, f"{rule.name} (Plus Size)", rule.minimum + 2, rule.maximum + 5, rule.keywords)
    if rule.primary == "Men's Clothing":
        return CategoryRule(rule.primary, f"{rule.name} (Plus Size)", rule.minimum + 3, rule.maximum + 3, rule.keywords)
    return rule


def classify_product(text: str) -> CategoryRule | None:
    normalized = _normalize(text)
    # A strong, unique subcategory phrase also determines its parent category.
    # This prevents words such as "Men's" in "Men's Necktie" from forcing the
    # product into Men's Clothing when the table places ties under Accessories.
    alias_matches = []
    rules_by_id = {rule.rule_id: rule for rule in CATEGORY_RULES}
    for rule_id, aliases in ALIASES.items():
        lengths = [len(_normalize(k)) for k in aliases if _contains(normalized, k)]
        if lengths:
            alias_matches.append((max(lengths), rules_by_id[rule_id]))
    if alias_matches:
        return _apply_plus_size(max(alias_matches, key=lambda item: item[0])[1], normalized)
    primary = infer_primary_category(normalized)
    candidates = rules_for_primary(primary) if primary else CATEGORY_RULES
    matches = []
    for rule in candidates:
        lengths = [len(_normalize(k)) for k in rule.keywords if _contains(normalized, k)]
        if lengths:
            matches.append((max(lengths), rule))
    return _apply_plus_size(max(matches, key=lambda item: item[0])[1], normalized) if matches else None


def infer_similar_category(text: str) -> tuple[CategoryRule | None, str | None]:
    rule = classify_product(text)
    return (rule, f"层级匹配：{rule.primary} → {rule.name}") if rule else (None, None)


def resolve_rule(value: str) -> CategoryRule | None:
    by_id = {rule.rule_id: rule for rule in CATEGORY_RULES}
    if value in by_id:
        return by_id[value]
    matches = [rule for rule in CATEGORY_RULES if rule.name == value]
    return matches[0] if len(matches) == 1 else None
