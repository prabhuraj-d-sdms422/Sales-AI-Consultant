## Use Case 2 (Pending): Allow “we have built / we have delivered” only when delivery is evidenced

### Goal
Enable the assistant to use completed-delivery language (e.g., **“we have built …”**, **“we have delivered …”**) *only* when we have a reliable signal that the relevant solution is already delivered for that use case.

### Current state (Use Case 1)
Right now, the system is configured to always use future/capability wording for solution recommendations (Use case 1), by:
- Updating the `solution_advisor` prompt + Pinecone RAG header to emphasize capability phrasing.
- Adding an output guardrail that rewrites accidental past-tense claims to future/capability form.

### Why this needs a “Use case 2” plan
If we permanently enforce “we can build” then the assistant can never truthfully confirm completed delivery later.
Conversely, if we permanently allow “we have built” then the assistant may mislead the client when delivery is not actually completed.

### What we need to do for Use Case 2
1. **Introduce a delivery-evidence signal in Pinecone metadata**
   - For each retrieved match/chunk (healthcare and insurance collections), add a metadata field such as:
     - `delivery_status: "delivered" | "planned"` (or similar)
   - If metadata is missing, default to the safer “planned/can build” behavior.

2. **Make `solution_advisor` choose tense based on evidence**
   - After Pinecone retrieval in `backend/app/agents/solution_advisor.py`, inspect returned `rag_sources`.
   - If evidence indicates `delivery_status == "delivered"` (for the best matches), generate past-tense language.
   - Otherwise keep future/capability language.

3. **Update prompts to support conditional tense**
   - Modify `backend/app/prompts/solution_advisor_prompt.py` to accept something like:
     - `{delivery_tense}` or `{claim_mode}`
   - Ensure the prompt instructs:
     - Use “we can build” when planned
     - Use “we have built / we have delivered” when delivered

4. **Adjust the output guardrail to be conditional**
   - Today’s guardrail rewrites past tense into future/capability unconditionally.
   - For Use case 2, update it so it only rewrites past tense when the system is still in “Use case 1 mode” (or when delivery evidence is absent).

5. **(Optional) Add a simple runtime toggle**
   - Add a setting like `CLAIM_TENSE_MODE=use_case_1|use_case_2` (env-driven) so you can switch behavior during rollout/testing.

### Acceptance criteria (when Use Case 2 is enabled)
- For conversations where Pinecone evidence says `delivery_status=delivered`, assistant responses may say:
  - “we have built …” / “we have delivered …”
- For conversations where evidence is `planned` or missing, assistant responses must not say:
  - “we have built …” / “we have delivered …”
- Guardrail behavior remains deterministic and logs any rewrites for analysis.

### Implementation notes / file touchpoints (expected later)
- `backend/app/services/rag_service.py`: include delivery metadata in `RAGSource`
- `backend/app/agents/solution_advisor.py`: determine delivery tense from `rag_sources`
- `backend/app/prompts/solution_advisor_prompt.py`: conditional tense instructions
- `backend/app/guardrails/output_guardrail.py`: make rewrite conditional (not always-on)

