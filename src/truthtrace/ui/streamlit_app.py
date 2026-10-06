"""Streamlit chat UI with evidence cards. Run: ``truthtrace ui``.

Models, the database and the in-memory index are created once per process with
``st.cache_resource``; each browser session keeps its own bounded chat history.
"""
from __future__ import annotations

import streamlit as st

from truthtrace.chat import BoundedHistory, ChatSession
from truthtrace.config import Settings, load_dotenv_if_present
from truthtrace.errors import ConfigError
from truthtrace.labels import Label
from truthtrace.runtime import build_services, configure_logging

st.set_page_config(page_title="truthtrace", page_icon=":mag:", layout="centered")

BADGE = {
    Label.TRUE: ":green[True]", Label.MOSTLY_TRUE: ":green[Mostly true]", Label.HALF_TRUE: ":orange[Half true]",
    Label.MOSTLY_FALSE: ":red[Mostly false]", Label.FALSE: ":red[False]", Label.PANTS_ON_FIRE: ":red[Pants on fire]",
    Label.UNVERIFIABLE: ":gray[Can't verify]",
}


@st.cache_resource
def services():
    load_dotenv_if_present()
    settings = Settings.from_env()
    configure_logging(settings)
    return build_services(settings)


try:
    svc = services()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

st.title("truthtrace")
st.caption("Checks claims against professional fact-checks. Verdicts come from the cited fact-checkers, "
           "or the tool says it can't verify. Always read the linked article.")
if svc.store.count() == 0:
    st.warning("The database is empty. Run `truthtrace ingest` (or `truthtrace demo`) first.")

if "chat" not in st.session_state:
    st.session_state.chat = ChatSession(svc.verifier, BoundedHistory(svc.settings.history_turns))
chat: ChatSession = st.session_state.chat


def render(result) -> None:
    if result.mode == "claim":
        st.markdown(f"**Verdict:** {BADGE[result.label]}  \n*{result.method.replace('_', ' ')}*")
    st.write(result.rationale)
    cards = result.citations or result.evidence[:3]
    for e in cards:
        with st.container(border=True):
            rating = f" · rated **{e.label.display}**" if e.label else ""
            when = e.published.strftime("%b %d, %Y") if e.published else "undated"
            st.markdown(f"[{e.id}] **[{e.title}]({e.url})**  \n{e.source} · {when}{rating}")
            if e.claim:
                st.caption(f"Claim checked: “{e.claim}”" + (f" ({e.speaker})" if e.speaker else ""))
    for note in result.notes:
        st.caption(f"Note: {note}")


for past in chat.results:
    st.chat_message("user").write(past.query)
    with st.chat_message("assistant"):
        render(past)

if prompt := st.chat_input("Paste a claim or ask about a fact-check"):
    st.chat_message("user").write(prompt)
    with st.chat_message("assistant"), st.spinner("Searching fact-checks..."):
        render(chat.send(prompt))
