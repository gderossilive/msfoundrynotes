# Microsoft Foundry Notes articles

This directory contains the English article sources and publication images for
the Microsoft Foundry Notes series. LinkedIn publication is manual; Markdown
image references are not uploaded automatically by the LinkedIn editor.

## Publication index

| Date | Article | Status |
| --- | --- | --- |
| 2026-10-01 | [From AI Ambition to Architecture Decisions](published/introduction.md) | Published on LinkedIn |
| 2026-10-02 | [Three Resources, One Model, No Agent Yet](published/episode-00a-foundry-core.md) | Published on LinkedIn |
| 2026-10-05 | [00a Chat Completions — One Prompt, One Role, One Response](published/episode-00a-chat-completions.md) | Published on LinkedIn |
| 2026-10-13 | [Private by Design, Reachable by Gateway](episode-00c-foundry-core-byo-vnet.md) | Scheduled |
| 2026-10-15 | [00c Chat Completions — One Blocked Call, One Policy, One Response](episode-00c-chat-completions.md) | Scheduled |
| 2026-10-17 | [00a Model Benchmark — Valid JSON, Wrong Priority](episode-00a-model-benchmark.md) | Scheduled |

## LinkedIn upload checklist

1. Upload the 1920 x 1080 cover in LinkedIn's dedicated cover area; do not
   insert it again in the article body.
2. Upload the companion diagram at the location of its Markdown image and keep
   the caption immediately below it.
3. Enter the alternative text from the table below.
4. Verify links, headings, image cropping, and the final LinkedIn preview.
5. After publication, record the LinkedIn URL in this index.

| Article | Cover | In-article image |
| --- | --- | --- |
| 00c Foundry Core | [Cover](images/00c-foundry-core-byo-vnet-cover.png) — "Microsoft Foundry Notes, episode 00c: Private by Design, Reachable by Gateway. Microsoft Foundry Core in a customer-managed VNet. Lane C, level 00." | [Network](images/00c-foundry-core-byo-vnet-network.png) — "A client with a Microsoft Entra ID token calls API Management Developer, which reaches a private Microsoft Foundry endpoint from a customer-managed VNet. Three private DNS zones resolve the Foundry names privately." |
| 00c Chat Completions | [Cover](images/00c-chat-completions-cover.png) — "Microsoft Foundry Notes, episode 00c Chat Completions: One Blocked Call, One Policy, One Response. A private Microsoft Foundry model reached through API Management. Lane C, level 00." | [Flow](images/00c-chat-completions-flow.png) — "Three steps: a direct call is blocked, the API Management policy validates the caller and changes identity, and the gateway reaches the model through the private endpoint." |
| 00a Model Benchmark | [Cover](images/00a-model-benchmark-cover.png) — "Microsoft Foundry Notes, episode 00a Model Benchmark: Valid JSON, Wrong Priority. What ten labeled documents revealed about classification. Lane A, level 00." | [Flow](images/00a-model-benchmark-flow.png) — "Ten synthetic documents are classified by gpt-4.1-mini and their predicted and reference labels are compared by four native Microsoft Foundry string-check graders." |

The technical implementation for each scheduled article is available from the
versioned release linked in that article's **Try it yourself** section.
