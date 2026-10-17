import type { Brief, Deck } from '../types';
import { assembleDeck, buildOutline, normalizeBrief } from '../algorithms/outline';

/** Synchronous compatibility helper for consumers of the former engine. */
export function createDemoDeck(source: Brief): Deck {
  const brief = normalizeBrief(source);
  return assembleDeck(buildOutline(brief), brief, new Date().toISOString());
}
