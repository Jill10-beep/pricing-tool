from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryRule:
    name: str
    minimum: float
    maximum: float
    keywords: tuple[str, ...]


CATEGORY_RULES: tuple[CategoryRule, ...] = (
    CategoryRule("女T恤", 19.99, 24.99, ("women's t-shirt", "womens t-shirt", "women t-shirt", "女t恤")),
    CategoryRule("男T恤", 22.99, 29.99, ("men's t-shirt", "mens t-shirt", "men t-shirt", "男t恤")),
    CategoryRule("女衬衫", 24.99, 32.99, ("women's shirt", "womens shirt", "women blouse", "women's blouse", "女衬衫")),
    CategoryRule("男Polo衫", 29.99, 39.99, ("men's polo", "mens polo", "男polo")),
    CategoryRule("男衬衫", 29.99, 39.99, ("men's shirt", "mens shirt", "男衬衫")),
    CategoryRule("女连衣裙", 34.99, 44.99, ("women's dress", "womens dress", "women dress", "女连衣裙")),
    CategoryRule("女半身裙", 24.99, 34.99, ("women's skirt", "womens skirt", "women skirt", "女半身裙")),
    CategoryRule("女卫衣", 34.99, 44.99, ("women's sweatshirt", "womens sweatshirt", "women hoodie", "women's hoodie", "女卫衣")),
    CategoryRule("女毛衣/针织衫", 34.99, 44.99, ("women's sweater", "womens sweater", "women knitwear", "women's knitwear", "women knit top", "女毛衣", "女针织衫")),
    CategoryRule("女牛仔裤", 34.99, 44.99, ("women's jeans", "womens jeans", "women jeans", "女牛仔裤")),
    CategoryRule("男卫衣", 39.99, 49.99, ("men's sweatshirt", "mens sweatshirt", "men hoodie", "men's hoodie", "男卫衣")),
    CategoryRule("男毛衣", 39.99, 49.99, ("men's sweater", "mens sweater", "men knitwear", "men's knitwear", "men knit top", "男毛衣")),
    CategoryRule("男牛仔裤", 39.99, 49.99, ("men's jeans", "mens jeans", "men jeans", "男牛仔裤")),
    CategoryRule("女长裤", 32.99, 44.99, ("women's pants", "womens pants", "women trousers", "women's trousers", "女长裤")),
    CategoryRule("男长裤", 34.99, 44.99, ("men's pants", "mens pants", "men trousers", "men's trousers", "男长裤")),
    CategoryRule("女短裤", 22.99, 29.99, ("women's shorts", "womens shorts", "women shorts", "女短裤")),
    CategoryRule("男短裤", 24.99, 34.99, ("men's shorts", "mens shorts", "men shorts", "男短裤")),
    CategoryRule("女套装", 39.99, 49.99, ("women's set", "womens set", "women two piece", "women's two piece", "女套装")),
    CategoryRule("运动鞋/跑鞋", 49.99, 69.99, ("running shoe", "running sneaker", "athletic shoe", "sports shoe", "运动鞋", "跑鞋")),
    CategoryRule("休闲鞋/乐福鞋", 39.99, 49.99, ("loafer", "casual shoe", "休闲鞋", "乐福鞋")),
    CategoryRule("凉鞋/平底鞋", 29.99, 39.99, ("sandal", "flat shoe", "ballet flat", "凉鞋", "平底鞋")),
    CategoryRule("靴子", 49.99, 69.99, ("boot", "boots", "靴子")),
    CategoryRule("耳饰", 6.99, 16.99, ("earring", "earrings", "ear cuff", "耳饰", "耳环")),
    CategoryRule("墨镜", 14.99, 24.99, ("sunglass", "sunglasses", "墨镜", "太阳镜")),
    CategoryRule("腰带", 14.99, 24.99, ("belt", "belts", "腰带")),
    CategoryRule("袜子", 9.99, 16.99, ("sock", "socks", "袜子")),
    CategoryRule("彩妆", 9.99, 24.99, ("makeup", "lipstick", "mascara", "eyeshadow", "foundation", "彩妆")),
    CategoryRule("护肤", 12.99, 39.99, ("skincare", "skin care", "serum", "moisturizer", "cleanser", "护肤")),
    CategoryRule("美容工具", 9.99, 29.99, ("beauty tool", "makeup brush", "eyelash curler", "美容工具")),
    CategoryRule("家具", 79.90, 99.90, ("furniture", "chair", "table", "sofa", "cabinet", "shelf", "家具", "椅", "桌", "沙发", "柜")),
)


def classify_product(text: str) -> CategoryRule | None:
    normalized = " ".join(str(text).lower().replace("_", "-").split())
    for rule in CATEGORY_RULES:
        if any(keyword in normalized for keyword in rule.keywords):
            return rule
    return None


SIMILAR_CATEGORY_ALIASES: tuple[tuple[str, str], ...] = (
    ("necktie", "腰带"), ("neck tie", "腰带"), ("bow tie", "腰带"), ("领带", "腰带"), ("领结", "腰带"),
    ("necklace", "耳饰"), ("bracelet", "耳饰"), ("ring", "耳饰"), ("项链", "耳饰"), ("手链", "耳饰"), ("戒指", "耳饰"),
    ("slipper", "凉鞋/平底鞋"), ("flip flop", "凉鞋/平底鞋"), ("拖鞋", "凉鞋/平底鞋"),
    ("tank top", "女T恤"), ("camisole", "女T恤"), ("吊带", "女T恤"), ("背心", "女T恤"),
    ("jacket", "男卫衣"), ("coat", "男卫衣"), ("夹克", "男卫衣"), ("外套", "男卫衣"),
    ("face mask", "护肤"), ("face cream", "护肤"), ("面膜", "护肤"), ("面霜", "护肤"),
    ("makeup sponge", "美容工具"), ("cotton pad", "美容工具"), ("粉扑", "美容工具"), ("化妆棉", "美容工具"),
)


def infer_similar_category(text: str) -> tuple[CategoryRule | None, str | None]:
    direct = classify_product(text)
    if direct is not None:
        return direct, "直接匹配"
    normalized = " ".join(str(text).lower().replace("_", "-").split())
    rules_by_name = {rule.name: rule for rule in CATEGORY_RULES}
    for keyword, target in SIMILAR_CATEGORY_ALIASES:
        if keyword in normalized:
            return rules_by_name[target], f"相似品类：{keyword} → {target}"
    return None, None
