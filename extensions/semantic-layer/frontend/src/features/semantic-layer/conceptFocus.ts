import { semanticLayerEvents } from './constants';

/** A glossary term or an expert rule to open, selected, in its own module. */
export type ConceptFocus = { module: 'glossary' | 'rules'; id: number };

let pendingFocus: ConceptFocus | null = null;

export function openConcept(focus: ConceptFocus) {
  pendingFocus = focus;
  window.dispatchEvent(new CustomEvent(semanticLayerEvents.moduleRequest, { detail: focus.module }));
}

/** The term or rule another module asked this one to select, handed out once. */
export function takeConceptFocus(module: ConceptFocus['module']): number | null {
  if (pendingFocus?.module !== module) return null;
  const { id } = pendingFocus;
  pendingFocus = null;
  return id;
}
