import { createDemoDeck } from '../engine';
import type { Brief, Deck } from '../types';

/** Integration seam. Replace this adapter with your backend client when it is ready. */
export interface PresentationService {
  createOutline(brief: Brief): Promise<Deck>;
}

export const presentationService: PresentationService = {
  async createOutline(brief) {
    return createDemoDeck(brief);
  },
};
