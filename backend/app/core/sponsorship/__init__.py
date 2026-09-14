"""Visa-sponsorship signal for job listings — a ranking boost, never a hard filter.

Two independent modules feed :func:`classify.classify`, strongest first:

* :mod:`register` — a match against the UK Home Office's public register of licensed
  Skilled Worker sponsors. Strong evidence: the employer genuinely holds a sponsor licence.
* :mod:`keywords` — explicit sponsorship language in the posting text. Weaker evidence (a
  posting can omit it truthfully), but it is the only signal available for the large share of
  employers whose registered legal entity cannot be resolved from a job board's display name.
"""
