import type { ReactElement } from "react";

/**
 * 目录系列示意插画（GX-01 … GX-32）。
 *
 * 边界（与 products/README.md 一致）：这些是**抽象线稿，不是商品实拍，也不还原
 * 具体颜色、材质、尺寸或型号**。仅按目录自带的系列编号（GX-xx）取形，
 * 不按商品名逐字猜测外形；页面保留"暂未提供商品图片"文案与
 * image_kind=placeholder 语义，任何消费者都不会把它当成实拍图。
 *
 * 服务端在 product_media 里按系列号给出 illustration key，前端只做渲染，
 * 不从商品名反推图片（沿用既有"不按商品名注入样例图"的约定）。
 */

const S = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

// 细节线（更细一档）
const T = { ...S, strokeWidth: 1.2 };

function Frame({ children }: { children: React.ReactNode }): ReactElement {
  return (
    <svg viewBox="0 0 96 96" role="img" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

/* ---------- 旅行装备 ---------- */
const backpack = (
  <Frame>
    <path {...S} d="M34 30v-6a14 14 0 0 1 28 0v6" />
    <rect {...S} x="26" y="28" width="44" height="46" rx="12" />
    <path {...S} d="M26 44h44" />
    <rect {...T} x="34" y="52" width="28" height="18" rx="5" />
    <path {...S} d="M38 28v-4M58 28v-4" />
    <path {...T} d="M22 40c-5 2-7 7-7 13v10M74 40c5 2 7 7 7 13v10" />
  </Frame>
);

const neck_pillow = (
  <Frame>
    <path {...S} d="M48 24c-12 0-20 8-20 18 0 8 5 13 12 13 4 0 6-2 8-6 2 4 4 6 8 6 7 0 12-5 12-13 0-10-8-18-20-18z" />
    <path {...T} d="M36 30c-5 3-8 8-8 14" />
    <ellipse {...T} cx="62" cy="52" rx="7" ry="5" />
  </Frame>
);

const suitcase = (
  <Frame>
    <path {...S} d="M40 22h16v8H40z" />
    <rect {...S} x="22" y="30" width="52" height="42" rx="7" />
    <path {...T} d="M22 46h52M42 30v42M54 30v42" />
    <circle {...S} cx="33" cy="78" r="3" />
    <circle {...S} cx="63" cy="78" r="3" />
  </Frame>
);

const compression_bag = (
  <Frame>
    <path {...S} d="M30 30h36l5 44H25z" />
    <path {...S} d="M30 30c0-6 8-10 18-10s18 4 18 10" />
    <path {...T} d="M25 46h46" />
    <path {...S} d="M42 58l-6 8h24l-6-8" />
    <path {...T} d="M48 44v22" />
  </Frame>
);

/* ---------- 数码配件 ---------- */
const gan_charger = (
  <Frame>
    <rect {...S} x="26" y="30" width="44" height="40" rx="9" />
    <path {...S} d="M38 30V18M58 30V18" />
    <path {...T} d="M38 22v8M58 22v8" />
    <rect {...T} x="36" y="46" width="10" height="6" rx="2" />
    <rect {...T} x="50" y="46" width="10" height="6" rx="2" />
    <path {...T} d="M40 60h16" />
  </Frame>
);

const earbuds = (
  <Frame>
    <path {...S} d="M34 26a7 7 0 0 1 7 7v6a7 7 0 0 1-14 0v-6a7 7 0 0 1 7-7z" />
    <path {...S} d="M34 46c-2 6-2 10-1 14h2c1-4 1-8 2-14" />
    <path {...S} d="M62 26a7 7 0 0 1 7 7v6a7 7 0 0 1-14 0v-6a7 7 0 0 1 7-7z" />
    <path {...S} d="M62 46c-2 6-2 10-1 14h2c1-4 1-8 2-14" />
    <rect {...S} x="38" y="66" width="20" height="16" rx="6" />
    <path {...T} d="M44 74h8" />
  </Frame>
);

const usb_hub = (
  <Frame>
    <rect {...S} x="18" y="38" width="56" height="20" rx="6" />
    <path {...T} d="M30 48h4M40 48h4M50 48h4" />
    <path {...S} d="M74 44h6v8h-6" />
    <path {...T} d="M26 58v10a6 6 0 0 0 6 6h32a6 6 0 0 0 6-6V58" />
  </Frame>
);

const power_bank = (
  <Frame>
    <rect {...S} x="28" y="24" width="40" height="52" rx="9" />
    <path {...T} d="M38 36h20M38 44h14" />
    <rect {...T} x="38" y="56" width="20" height="10" rx="3" />
    <path {...S} d="M44 62h8" />
  </Frame>
);

/* ---------- 家居生活 ---------- */
const curtain = (
  <Frame>
    <path {...S} d="M20 24h56" />
    <path {...S} d="M28 24v50c8 0 12-8 12-18V24" />
    <path {...S} d="M68 24v50c-8 0-12-8-12-18V24" />
    <path {...T} d="M22 80h52" />
    <path {...T} d="M28 30h12M56 30h12" />
  </Frame>
);

const mug = (
  <Frame>
    <path {...S} d="M30 30h30v30a12 12 0 0 1-12 12h-6a12 12 0 0 1-12-12z" />
    <path {...S} d="M60 38h5a8 8 0 0 1 0 16h-5" />
    <path {...T} d="M30 42h30" />
    <path {...T} d="M22 78h46" />
  </Frame>
);

const storage_box = (
  <Frame>
    <rect {...S} x="22" y="34" width="52" height="34" rx="6" />
    <path {...S} d="M18 34h60l-4-8H22z" />
    <path {...T} d="M22 50h52" />
    <path {...S} d="M42 44h12v10H42z" />
  </Frame>
);

const drying_rack = (
  <Frame>
    <path {...S} d="M22 30h52" />
    <path {...S} d="M30 30l14 48M66 30L52 78" />
    <path {...S} d="M36 52h24" />
    <path {...T} d="M26 78h16M54 78h16" />
    <path {...T} d="M40 30v8c0 3 6 3 6-2M56 30v6" />
  </Frame>
);

/* ---------- 户外运动 ---------- */
const camping_lantern = (
  <Frame>
    <path {...S} d="M40 22h16" />
    <path {...S} d="M34 30h28l-4 8H38z" />
    <rect {...S} x="34" y="38" width="28" height="26" rx="7" />
    <path {...T} d="M48 38v26" />
    <path {...S} d="M36 64h24l3 10H33z" />
    <path {...T} d="M30 46l-6-4M66 46l6-4M30 58l-8 2M66 58l8 2" />
  </Frame>
);

const trekking_pole = (
  <Frame>
    <rect {...S} x="40" y="16" width="12" height="22" rx="6" />
    <path {...S} d="M46 38v22M46 60v18" />
    <path {...T} d="M42 46h8M40 54h12" />
    <path {...S} d="M46 78l-6 8h12z" />
    <path {...T} d="M52 20c6 2 8 6 8 10" />
  </Frame>
);

const sleeping_bag = (
  <Frame>
    <path {...S} d="M34 22h20c8 0 12 6 12 14v38c0 6-4 8-10 8H38c-6 0-8-4-8-10V36c0-8 4-14 4-14z" />
    <path {...T} d="M34 22c-4 6-4 12-4 20v40" />
    <path {...S} d="M48 34v40" />
    <path {...T} d="M54 42c4 0 6 2 6 6s-2 6-6 6" />
    <ellipse {...T} cx="42" cy="30" rx="6" ry="5" />
  </Frame>
);

const thermos = (
  <Frame>
    <path {...S} d="M40 24h16v6H40z" />
    <path {...S} d="M38 30h20v44a6 6 0 0 1-6 6H44a6 6 0 0 1-6-6z" />
    <path {...T} d="M38 44h20" />
    <path {...T} d="M38 56h20M44 62h8" />
  </Frame>
);

/* ---------- 美妆个护 ---------- */
const shaver = (
  <Frame>
    <path {...S} d="M34 26h28v14a6 6 0 0 1-6 6H40a6 6 0 0 1-6-6z" />
    <path {...T} d="M42 26v14M54 26v14" />
    <path {...S} d="M42 46h12v26a6 6 0 0 1-6 6 6 6 0 0 1-6-6z" />
    <path {...T} d="M44 58h8" />
  </Frame>
);

const travel_bottles = (
  <Frame>
    <rect {...S} x="26" y="34" width="16" height="40" rx="5" />
    <path {...S} d="M30 34v-6h8v6" />
    <rect {...S} x="52" y="42" width="14" height="32" rx="5" />
    <path {...S} d="M56 42v-6h6v6" />
    <path {...T} d="M30 46h8M56 52h6" />
  </Frame>
);

const hair_dryer = (
  <Frame>
    <rect {...S} x="22" y="30" width="40" height="26" rx="13" />
    <path {...S} d="M62 36h8a5 5 0 0 1 0 12h-8z" />
    <path {...S} d="M36 56v8a8 8 0 0 0 8 8h4a8 8 0 0 0 8-8v-8" />
    <path {...T} d="M32 36h20M32 44h14" />
    <path {...T} d="M28 24c2-4 12-5 20-3" />
  </Frame>
);

const face_towel = (
  <Frame>
    <path {...S} d="M24 40h48v10a6 6 0 0 1-6 6H30a6 6 0 0 1-6-6z" />
    <path {...S} d="M24 56h48v10a6 6 0 0 1-6 6H30a6 6 0 0 1-6-6z" />
    <path {...T} d="M24 46h48M24 62h48" />
    <path {...S} d="M34 34c4-4 24-4 28 0" />
    <path {...T} d="M40 30c2-3 14-3 16 0" />
  </Frame>
);

/* ---------- 厨房餐饮 ---------- */
const lunch_box = (
  <Frame>
    <rect {...S} x="22" y="36" width="52" height="34" rx="7" />
    <path {...S} d="M20 30h56v8H20z" />
    <path {...T} d="M22 52h52" />
    <path {...S} d="M34 30v-6a6 6 0 0 1 6-6h16a6 6 0 0 1 6 6v6" />
  </Frame>
);

const cutlery = (
  <Frame>
    <path {...S} d="M34 26v16a6 6 0 0 0 12 0V26" />
    <path {...S} d="M40 26v6" />
    <path {...S} d="M40 48v22" />
    <path {...S} d="M62 26c-5 2-8 8-8 16 0 6 3 8 8 8z" />
    <path {...S} d="M62 26v44" />
  </Frame>
);

const pour_over_kettle = (
  <Frame>
    <path {...S} d="M30 40h32v22a10 10 0 0 1-10 10H40a10 10 0 0 1-10-10z" />
    <path {...S} d="M58 44c8-2 10-12 6-20-3-6-2-8 2-8" />
    <path {...S} d="M30 46H22a6 6 0 0 0 0 12h8" />
    <path {...T} d="M34 34h24" />
  </Frame>
);

const food_bag = (
  <Frame>
    <path {...S} d="M28 34h40l-4 42H32z" />
    <path {...S} d="M28 34l6-12h28l6 12" />
    <path {...T} d="M28 44h40" />
    <path {...T} d="M40 56h16" />
  </Frame>
);

/* ---------- 办公学习 ---------- */
const desk_lamp = (
  <Frame>
    <path {...S} d="M40 22h16l10 16H30z" />
    <path {...S} d="M48 38v30" />
    <path {...S} d="M34 68h28l4 8H30z" />
    <path {...T} d="M26 50h-9M79 50h-9M31 34l-7-7M65 34l7-7" />
  </Frame>
);

const laptop_stand = (
  <Frame>
    <path {...S} d="M28 62h40l-4-24H32z" />
    <path {...S} d="M28 62h40l6 10H22z" />
    <path {...T} d="M36 44h24" />
    <path {...S} d="M34 62V40a4 4 0 0 1 4-4h20a4 4 0 0 1 4 4v22" />
  </Frame>
);

const mouse = (
  <Frame>
    <path {...S} d="M48 24c11 0 18 10 18 24s-7 24-18 24-18-10-18-24 7-24 18-24z" />
    <path {...T} d="M48 24v20" />
    <path {...S} d="M48 34v6" />
    <path {...T} d="M30 48h36" />
  </Frame>
);

const document_folder = (
  <Frame>
    <path {...S} d="M22 30h20l6 8h26v34a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4z" />
    <path {...S} d="M34 20h28v18H34z" />
    <path {...T} d="M40 26h16M40 32h12" />
  </Frame>
);

/* ---------- 母婴宠物 ---------- */
const pet_carrier = (
  <Frame>
    <path {...S} d="M26 40h44v26a10 10 0 0 1-10 10H36a10 10 0 0 1-10-10z" />
    <path {...S} d="M26 40c0-10 10-16 22-16s22 6 22 16" />
    <rect {...T} x="36" y="48" width="24" height="16" rx="4" />
    <path {...T} d="M40 48v16M48 48v16M56 48v16" />
    <path {...S} d="M36 24l-4-6M60 24l4-6" />
  </Frame>
);

const pet_waterer = (
  <Frame>
    <path {...S} d="M38 20h20v10H38z" />
    <path {...S} d="M36 30h24v22a8 8 0 0 1-8 8H44a8 8 0 0 1-8-8z" />
    <path {...T} d="M36 42h24" />
    <path {...S} d="M22 64h52l-6 14H28z" />
    <path {...T} d="M48 60v10" />
  </Frame>
);

const baby_towel = (
  <Frame>
    <rect {...S} x="24" y="30" width="48" height="34" rx="8" />
    <path {...T} d="M24 42h48M24 54h48" />
    <path {...T} d="M40 30v34M56 30v34" />
    <circle {...S} cx="48" cy="22" r="8" />
    <path {...T} d="M45 22h6M48 19v6" />
  </Frame>
);

const pet_brush = (
  <Frame>
    <path {...S} d="M30 34h36v16a8 8 0 0 1-8 8H38a8 8 0 0 1-8-8z" />
    <path {...T} d="M34 58v8M42 58v10M50 58v10M58 58v8" />
    <path {...S} d="M40 26h16v8H40z" />
    <path {...T} d="M48 26v8" />
  </Frame>
);

const SERIES_ILLUSTRATIONS: Record<string, ReactElement> = {
  "01": backpack,
  "02": neck_pillow,
  "03": suitcase,
  "04": compression_bag,
  "05": gan_charger,
  "06": earbuds,
  "07": usb_hub,
  "08": power_bank,
  "09": curtain,
  "10": mug,
  "11": storage_box,
  "12": drying_rack,
  "13": camping_lantern,
  "14": trekking_pole,
  "15": sleeping_bag,
  "16": thermos,
  "17": shaver,
  "18": travel_bottles,
  "19": hair_dryer,
  "20": face_towel,
  "21": lunch_box,
  "22": cutlery,
  "23": pour_over_kettle,
  "24": food_bag,
  "25": desk_lamp,
  "26": laptop_stand,
  "27": mouse,
  "28": document_folder,
  "29": pet_carrier,
  "30": pet_waterer,
  "31": baby_towel,
  "32": pet_brush,
};

export function hasSeriesIllustration(key?: string | null): boolean {
  return !!key && key in SERIES_ILLUSTRATIONS;
}

export function SeriesIllustration({ seriesKey }: { seriesKey?: string | null }): ReactElement | null {
  if (!seriesKey) return null;
  return SERIES_ILLUSTRATIONS[seriesKey] ?? null;
}
