from app.sources.screener import parse
from app.push.classify import rule_classify
from app.push.digest import headline

def test_transcripts_use_current_link_markup():
    html = '<div id="documents"><div class="concalls"><li><div>Nov 2026</div><a class="button-chip" href="https://example.com/report.pdf">Transcript</a><button>AI Summary</button></li></div></div>'
    assert parse(html, "TEST", "https://example.com")["docs"]["concalls"][0]["transcript"] == "https://example.com/report.pdf"

def test_debt_redemption_is_not_fundraising():
    assert rule_classify({"headline": "Commercial Paper", "text": "Redemption of Commercial Paper"}) == ("press_release", "debt_repayment")

def test_dismissed_items_excluded_from_headline():
    assert "Nothing needs you" in headline([{"tier":"act","state":"done","category":"results"}], [])
