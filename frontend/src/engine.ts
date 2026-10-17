// Compatibility facade. New code imports the owning module directly.
export { templates, EXAMPLE_BRIEF } from './data/templates';
export { auditDeck, fixIssue } from './algorithms/audit';
export { getSlideTypography } from './algorithms/typography';
export { importTemplate } from './rendering/templateImport';
export { exportHtml, exportPrint, exportPptx } from './rendering/export';
export { createDemoDeck } from './pipeline/localDeck';
