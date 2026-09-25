import React from 'react';
import type { Asset } from '../../types/portfolio';

const assetColor: Record<Asset, string> = {
  BTC: '#f2a33a',
  ETH: '#a3aee0',
  SOL: '#b58cf5',
  HYPE: '#5fd4bf'
};

export function AssetGlyph({ asset }: {asset: Asset;}) {
  const color = assetColor[asset];
  return (
    <span
      aria-hidden="true"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
      style={{ backgroundColor: `${color}1f`, color }}>
      
      {asset.charAt(0)}
    </span>);

}