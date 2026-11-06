"""Claude explains a chart (web/claude.py): from the chart's facts only, as text beside it.

The Anthropic API isn't called here (a stand-in client answers), so these tests prove what is
sent and what is accepted, not what the live model writes."""

import json

import pytest
from conftest import needs_lilypond

from drum_agent.charts import compile_spec
from drum_agent.web import claude, providers

GROOVE = {"hh": "x-x-x-x-", "sn": "--x---x-", "bd": "x---x---"}
ANSWER = {
    "summary": "An eight-bar groove at 100 BPM in two sections.",
    "practice_plan": [{"title": "The groove", "first_bar": 1, "last_bar": 4, "how": "Start at 70%, bars 1-4, then speed up."},
                      {"title": "The ending", "first_bar": 8, "last_bar": 8, "how": "Slowly, until it's even."}],
    "watch_out": ["Bar 3 is flagged: check it by ear."],
}


class Messages:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kw):
        self.calls.append(kw)
        block = type("B", (), {"type": "text", "text": self.text})()
        usage = type("U", (), {"input_tokens": 500, "output_tokens": 200})()
        return type("R", (), {"content": [block], "stop_reason": self.stop_reason, "usage": usage, "model": kw["model"]})()


def fake(answer, stop_reason="end_turn"):
    messages = Messages(answer if isinstance(answer, str) else json.dumps(answer), stop_reason)
    return type("C", (), {"beta": type("Beta", (), {"messages": messages})()})()


def song():
    s = compile_spec({"title": "Test Song", "artist": "Tester", "tempo": 100, "rights": "original",
                      "sections": [{"label": "A", "bars": [GROOVE] * 4}, {"label": "B", "bars": [GROOVE] * 4}]})
    s.measures[2].uncertain = True
    s.measures[7].cue = "Fill"
    s.source = r"C:\Users\someone\Music\secret take.wav"
    return s


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DRUM_AGENT_ANTHROPIC_MODEL", "test-model")


def test_the_facts_are_what_the_chart_says():
    f = claude.chart_facts(song())
    assert f["bars"] == 8 and f["tempo_bpm"] == 100 and f["time_signatures"] == ["4/4"]
    assert f["bars_flagged_as_unsure"] == [3] and f["fill_bars"] == [8]
    assert f["strokes_per_instrument"] == {"hihat": 32, "snare": 16, "kick": 16}
    assert [s["first_bar"] for s in f["sections"]] == [1, 5]
    assert len(f["busiest_bars"]) == 5
    json.dumps(f)  # it goes in a prompt


def test_claude_gets_the_facts_and_nothing_else(configured):
    client = fake(ANSWER)
    out = claude.explain_chart(song(), client=client)
    assert out["summary"] == ANSWER["summary"] and out["model"] == "test-model"
    assert [(s["first_bar"], s["last_bar"]) for s in out["practice_plan"]] == [(1, 4), (8, 8)]
    assert out["watch_out"] == ANSWER["watch_out"] and out["usage"]["output_tokens"] == 200
    sent = client.beta.messages.calls[0]
    text = sent["messages"][0]["content"]
    assert sent["output_config"]["format"]["schema"] == claude.EXPLAIN_SCHEMA
    assert sent["max_tokens"] >= 16000 and sent["fallbacks"] == "default"  # room for thinking; refusal fallback
    assert "haven't heard the recording" in text and '"bars_flagged_as_unsure": [\n  3\n ]' in text
    assert "secret take" not in json.dumps(sent) and "test-key" not in json.dumps(sent)


@pytest.mark.parametrize("change, why", [
    ({"practice_plan": []}, "no summary or practice plan"),
    ({"summary": "  "}, "no summary or practice plan"),
    ({"practice_plan": [{"title": "x", "first_bar": 7, "last_bar": 12, "how": "y"}]}, "names bars 7 to 12"),
    ({"practice_plan": [{"title": "x", "first_bar": 5, "last_bar": 2, "how": "y"}]}, "names bars 5 to 2"),
    ({"practice_plan": [{"title": "x", "first_bar": "1", "last_bar": 2, "how": "y"}]}, "names bars 1 to 2"),
    ({"summary": "The hard part is bar 42."}, "bar 42"),
    ({"watch_out": ["Listen to bars 7-9."]}, "bars 7-9"),
    ({"watch_out": ["Bars 0 to 2 are unclear."]}, "Bars 0 to 2"),
])
def test_an_answer_that_does_not_fit_the_chart_is_not_shown(configured, change, why):
    with pytest.raises(claude.ClaudeUnavailable, match=why) as exc:
        claude.explain_chart(song(), client=fake({**ANSWER, **change}))
    assert exc.value.code == "invalid_answer"


def test_long_answers_are_cut_and_a_refusal_is_said_plainly(configured):
    long = {**ANSWER, "summary": "x" * 5000, "watch_out": ["y"] * 9,
            "practice_plan": [{"title": "t", "first_bar": 1, "last_bar": 1, "how": "z"}] * 9}
    out = claude.explain_chart(song(), client=fake(long))
    assert len(out["summary"]) == 800 and len(out["watch_out"]) == 4 and len(out["practice_plan"]) == 6
    with pytest.raises(claude.ClaudeUnavailable) as exc:
        claude.explain_chart(song(), client=fake("", "refusal"))
    assert exc.value.code == "refused"


@needs_lilypond
def test_the_studio_keeps_the_answer_with_its_version_and_changes_nothing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from drum_agent.web.app import create_app
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(tmp_path / "data", providers=providers.Providers(
        spotify=providers.Spotify(None, None), youtube=providers.YouTube(None), public=False))
    with TestClient(app) as c:
        sid = c.post("/api/songs", json={"title": "Test Song", "artist": "Tester"}).json()["song"]["id"]
        cid = app.state.runner._save_chart(app.state.store.get_song(sid), song(), lambda stage: None, origin="library_chart")["id"]
        before = c.get(f"/api/charts/{cid}/files/chart.json").content
        # Not configured: said so, nothing made up, nothing kept.
        r = c.post(f"/api/charts/{cid}/explain")
        assert r.status_code == 503 and r.json()["error"] == "not_configured"
        calls = []

        def answer(score, client=None):
            calls.append(score)
            return {**ANSWER, "model": "test-model", "usage": {}}
        monkeypatch.setattr(claude, "explain_chart", answer)
        first = c.post(f"/api/charts/{cid}/explain").json()
        again = c.post(f"/api/charts/{cid}/explain").json()
        assert first["kept"] is False and again["kept"] is True and again["explanation"] == first["explanation"]
        assert len(calls) == 1  # asking again costs nothing
        assert c.get(f"/api/charts/{cid}/files/chart.json").content == before
        assert [x["version"] for x in c.get(f"/api/projects/{sid}").json()["charts"]] == [1]
        assert c.post("/api/charts/ch_0123456789abcdef/explain").status_code == 404
