# Prompt templates

Plain-text prompt templates used for AI analysis. To customise one without
editing the app, copy it to `<data_dir>/prompts/<same path>`; user copies win.
Add a new summary style by dropping a new `summary/<name>.md` file there.

Placeholders: `{{context}}` (meeting header + notes + transcript, built from
`_context.md`), `{{title}}`, `{{date}}`, `{{duration}}`, `{{attendees}}`,
`{{notes}}`, `{{highlights}}`, `{{transcript}}`, `{{language_instruction}}`,
`{{question}}`, `{{doc_type}}`, `{{excerpts}}`, `{{part}}`.

If the first line of a summary template is `<!-- label: ... -->`, that text
is shown as the template name in the app.
