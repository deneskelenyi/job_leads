# Applicant profile — copy to data/profile.md and fill in your own background.
# data/ is gitignored: your profile never leaves your machine.
# This file feeds the letter-drafting prompt verbatim, so write it as facts
# the LLM may use — never let it invent beyond what is written here.

Name: <your name>
Title: <e.g. Senior Backend Engineer>
Location: <city/country, UTC offset>, <remote / hybrid / on-site>, <languages>, <availability>

Background: <years> years of <your domains>.
<2-4 lines of career history: employers or client types, the systems you owned,
 the scale, the outcomes. Be concrete — these facts are what the letters use.>

Skills: <primary languages, frameworks, infra, data stores, tooling —
 the same terms your scoring keywords in config.yaml target.>

Differentiator: <what makes you unusual — e.g. daily agentic-AI tooling practice,
 rare domain depth, track record of X.>

Writing rules (non-negotiable):
- First person, plain, professional. NO enthusiasm filler: never use
  "excited", "thrilled", "wonderful opportunity", "passionate about", or similar.
- Open by grounding your fit in your strongest, most relevant ownership claim.
- Lead with the skills from this profile that the job actually asks for.
- Close with: location/timezone, work mode, language fluency, availability,
  and an invitation to a conversation. Do NOT offer to walk the reader through
  live systems or give a demo.
- Do NOT state restrictions (travel, on-call, hours) — those belong in a recruiter call.
- Ground EVERY claim in the profile text. Never invent employers, projects, dates,
  numbers, or skills. If the job asks for something not in the profile, do not
  claim it; you may say you have adjacent experience if the profile supports it.
- Length: 180-260 words. Output ONLY the letter body (no subject line, no headers).
