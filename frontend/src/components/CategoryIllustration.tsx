import type { ReactElement } from "react";
import { SeriesIllustration, hasSeriesIllustration } from "./SeriesIllustrations";

/**
 * 品类插画占位：仅用于"目录未提供商品图片"的商品，按品类给出统一的线稿示意。
 *
 * 边界：这些是**抽象示意图，不是任何商品的实拍或外观还原**，因此
 *  - 不描绘具体颜色/材质/尺寸（页面同时保留"暂未提供商品图片"文案）；
 *  - 只按品类取形，不按商品名或 ID 猜测外形，避免暗示具体型号特征。
 */

type Props = {
  category?: string | null;
  /** 目录系列键（GX-xx 序号）：存在时优先展示产品级线稿 */
  seriesKey?: string | null;
  className?: string;
};

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function Frame({ children }: { children: React.ReactNode }): ReactElement {
  return (
    <svg viewBox="0 0 96 96" role="img" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

// 旅行装备：行李箱
function TravelIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M38 24h20v8H38z" />
      <rect {...STROKE} x="22" y="32" width="52" height="40" rx="7" />
      <path {...STROKE} d="M22 48h52M42 32v40M54 32v40" />
      <circle {...STROKE} cx="34" cy="78" r="3.2" />
      <circle {...STROKE} cx="62" cy="78" r="3.2" />
      <path {...STROKE} d="M30 72v3M66 72v3" />
    </Frame>
  );
}

// 数码配件：头戴式耳机
function DigitalIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M24 56V48a24 24 0 0 1 48 0v8" />
      <rect {...STROKE} x="16" y="52" width="14" height="22" rx="6" />
      <rect {...STROKE} x="66" y="52" width="14" height="22" rx="6" />
      <path {...STROKE} d="M30 74v4a8 8 0 0 0 8 8h8" />
      <circle {...STROKE} cx="50" cy="86" r="3" />
    </Frame>
  );
}

// 家居生活：台灯
function HomeIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M40 22h16l10 16H30z" />
      <path {...STROKE} d="M48 38v30" />
      <path {...STROKE} d="M34 68h28l4 8H30z" />
      <path {...STROKE} d="M26 50h-9M79 50h-9M31 34l-7-7M65 34l7-7" />
    </Frame>
  );
}

// 户外运动：帐篷与山
function OutdoorIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M20 72l20-34 20 34z" />
      <path {...STROKE} d="M40 72V56l8-8 8 8v16" />
      <path {...STROKE} d="M56 72l14-22 14 22z" />
      <circle {...STROKE} cx="70" cy="26" r="6" />
      <path {...STROKE} d="M12 72h72" />
    </Frame>
  );
}

// 厨房餐饮：杯与碟
function KitchenIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M28 34h40v22a12 12 0 0 1-12 12H40a12 12 0 0 1-12-12z" />
      <path {...STROKE} d="M68 40h6a7 7 0 0 1 0 14h-6" />
      <path {...STROKE} d="M24 76h48" />
      <path {...STROKE} d="M40 24c0-3 3-3 3-6M50 24c0-3 3-3 3-6" />
    </Frame>
  );
}

// 办公学习：摊开的书与笔
function OfficeIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M48 34c-6-5-14-7-22-7v38c8 0 16 2 22 7 6-5 14-7 22-7V27c-8 0-16 2-22 7z" />
      <path {...STROKE} d="M48 34v38" />
      <path {...STROKE} d="M62 62l14-14 6 6-14 14-8 2z" />
    </Frame>
  );
}

// 母婴宠物：爪印
function BabyPetIcon(): ReactElement {
  return (
    <Frame>
      <ellipse {...STROKE} cx="48" cy="62" rx="16" ry="13" />
      <ellipse {...STROKE} cx="28" cy="42" rx="6" ry="8" />
      <ellipse {...STROKE} cx="42" cy="32" rx="6" ry="8" />
      <ellipse {...STROKE} cx="56" cy="32" rx="6" ry="8" />
      <ellipse {...STROKE} cx="68" cy="42" rx="6" ry="8" />
    </Frame>
  );
}

// 美妆个护：滴管瓶与圆镜
function BeautyIcon(): ReactElement {
  return (
    <Frame>
      <rect {...STROKE} x="30" y="34" width="24" height="40" rx="6" />
      <path {...STROKE} d="M38 34v-8h8v8" />
      <path {...STROKE} d="M42 18v8" />
      <circle {...STROKE} cx="68" cy="42" r="12" />
      <path {...STROKE} d="M76 50l6 6" />
      <path {...STROKE} d="M36 52h12" />
    </Frame>
  );
}

// 未知品类：购物袋（与既有图标语义一致）
function DefaultIcon(): ReactElement {
  return (
    <Frame>
      <path {...STROKE} d="M28 34h40l4 42H24z" />
      <path {...STROKE} d="M38 34v-6a10 10 0 0 1 20 0v6" />
    </Frame>
  );
}

const BY_CATEGORY: Record<string, () => ReactElement> = {
  旅行装备: TravelIcon,
  数码配件: DigitalIcon,
  家居生活: HomeIcon,
  户外运动: OutdoorIcon,
  厨房餐饮: KitchenIcon,
  办公学习: OfficeIcon,
  母婴宠物: BabyPetIcon,
  美妆个护: BeautyIcon,
};

export function CategoryIllustration({ category, seriesKey = null, className = "" }: Props): ReactElement {
  // 产品级系列线稿优先；没有系列键时退回品类线稿，最后才是通用图标。
  // 注意：React 元素对象恒为真值，必须用 key 是否存在来判断，不能写 `series ?? fallback`。
  const hasSeries = hasSeriesIllustration(seriesKey);
  const Illustration = (category && BY_CATEGORY[category]) || DefaultIcon;
  return (
    <span
      className={`category-illustration ${className}`}
      data-category={category || "default"}
      data-series={hasSeries ? seriesKey : "none"}
    >
      {hasSeries ? <SeriesIllustration seriesKey={seriesKey} /> : <Illustration />}
    </span>
  );
}
