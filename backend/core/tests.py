from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import ClothRoll, DipRun, Loft

SH = ZoneInfo("Asia/Shanghai")
User = get_user_model()


def sh_dt(date_text, hour, minute=0):
    return datetime.fromisoformat(f"{date_text}T{hour:02d}:{minute:02d}:00").replace(tzinfo=SH)


class TodayGroupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.loft = Loft.objects.create(name="测试间")
        self.roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-T", status=ClothRoll.STATUS_DIPPING
        )

    def test_today_endpoint_uses_server_natural_day(self):
        from django.utils import timezone

        today = timezone.localdate()
        DipRun.objects.create(
            roll=self.roll, started_at=sh_dt(today.isoformat(), 0, 30),
            resin_pct=Decimal("28"),
        )
        DipRun.objects.create(
            roll=self.roll, started_at=sh_dt(today.isoformat(), 23, 50),
            resin_pct=Decimal("28"),
        )
        yesterday = (today - timedelta(days=1)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        DipRun.objects.create(
            roll=self.roll, started_at=sh_dt(yesterday, 23, 50),
            resin_pct=Decimal("28"),
        )
        DipRun.objects.create(
            roll=self.roll, started_at=sh_dt(tomorrow, 0, 10),
            resin_pct=Decimal("28"),
        )

        resp = self.client.get("/api/dips/today/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["today"], today.isoformat())
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["results"]), 2)
        for row in body["results"]:
            self.assertEqual(row["dayKey"], today.isoformat())

    @override_settings(TIME_ZONE="Asia/Shanghai")
    def test_day_key_folds_by_shanghai_wall_clock_not_utc(self):
        # 00:30 上海 = 前一天 16:30 UTC；按 UTC 折叠会错进昨天组
        DipRun.objects.create(
            roll=self.roll, started_at=sh_dt("2026-10-04", 0, 30),
            resin_pct=Decimal("28"),
        )
        row = self.client.get("/api/dips/").json()["results"][0]
        self.assertEqual(row["dayKey"], "2026-10-04")

    def test_cross_worker_writes_same_roll_counts_match_db(self):
        """两名浸胶工交叉给同一卷各写一笔：今天组、挂签增量、全库都对得上。"""
        before = self.client.get("/api/dips/today/").json()["count"]
        total_before = DipRun.objects.count()

        payload = {
            "rollId": self.roll.id,
            "resinPct": "28.00",
            "cureHours": None,
            "notes": "",
        }
        # 两人提交时间相同（交叉写入），靠 -id 兜底稳定排序
        from django.utils import timezone

        ts = timezone.now().replace(microsecond=0).isoformat()
        r1 = self.client.post("/api/dips/", {**payload, "startedAt": ts}, format="json")
        r2 = self.client.post("/api/dips/", {**payload, "startedAt": ts}, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r2.status_code, 201, r2.content)

        today_resp = self.client.get("/api/dips/today/").json()
        self.assertEqual(today_resp["count"], before + 2)

        rolls = self.client.get(f"/api/rolls/{self.roll.id}/").json()
        self.assertEqual(rolls["dipCount"], 2)

        listing = self.client.get("/api/dips/").json()
        self.assertEqual(listing["count"], total_before + 2)
        self.assertEqual(DipRun.objects.count(), total_before + 2)

    def test_posted_with_shanghai_offset_lands_in_today_group(self):
        from django.utils import timezone

        today = timezone.localdate().isoformat()
        # 浏览器只知道墙钟，显式带 +08:00 提交
        resp = self.client.post(
            "/api/dips/",
            {
                "rollId": self.roll.id,
                "startedAt": f"{today}T00:05:00+08:00",
                "resinPct": "28.00",
                "cureHours": None,
                "notes": "",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.client.get("/api/dips/today/").json()["count"], 1)

    def test_serialized_started_at_carries_offset(self):
        DipRun.objects.create(
            roll=self.roll, started_at=sh_dt("2026-10-04", 9, 0),
            resin_pct=Decimal("28"),
        )
        row = self.client.get("/api/dips/").json()["results"][0]
        self.assertIn("+08:00", row["startedAt"])
        self.assertEqual(row["dayKey"], "2026-10-04")
