from datetime import datetime, time, timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ClothRoll, DipRun, Loft
from .serializers import ClothRollSerializer, DipRunSerializer, LoftSerializer


class LoftViewSet(viewsets.ModelViewSet):
    queryset = Loft.objects.annotate(roll_count=Count("rolls")).all()
    serializer_class = LoftSerializer


class ClothRollViewSet(viewsets.ModelViewSet):
    serializer_class = ClothRollSerializer

    def get_queryset(self):
        # dip_count 直接来自库聚合，供挂签展示「本卷总条数」
        qs = ClothRoll.objects.select_related("loft").annotate(
            dip_count=Count("dip_runs")
        )
        loft_id = self.request.query_params.get("loftId")
        status = self.request.query_params.get("status")
        if loft_id:
            qs = qs.filter(loft_id=loft_id)
        if status:
            qs = qs.filter(status=status)
        return qs


class DipRunViewSet(viewsets.ModelViewSet):
    serializer_class = DipRunSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = DipRun.objects.select_related("roll", "roll__loft").all()
        roll_id = self.request.query_params.get("rollId")
        if roll_id:
            qs = qs.filter(roll_id=roll_id)
        return qs

    @action(detail=False, methods=["get"])
    def today(self, request):
        """服务器时区(Asia/Shanghai)自然日「今天组」。

        用带时区的 [今日00:00, 次日00:00) 区间过滤，跨后端都按服务器
        自然日折叠；count 直接由数据库聚合，不信任前端分页数组长度。
        """
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time.min))
        end = start + timedelta(days=1)
        qs = (
            self.filter_queryset(self.get_queryset())
            .filter(started_at__gte=start, started_at__lt=end)
            .order_by("-started_at", "-id")
        )
        total = qs.count()
        page = self.paginate_queryset(qs)
        rows = page if page is not None else list(qs)
        return Response(
            {
                "today": today.isoformat(),
                "count": total,
                "results": self.get_serializer(rows, many=True).data,
            }
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    data = {
        "loftCount": Loft.objects.count(),
        "rawRollCount": ClothRoll.objects.filter(status=ClothRoll.STATUS_RAW).count(),
        "dippingRollCount": ClothRoll.objects.filter(
            status=ClothRoll.STATUS_DIPPING
        ).count(),
        "curedRollCount": ClothRoll.objects.filter(status=ClothRoll.STATUS_CURED).count(),
        "dipRunCount": DipRun.objects.count(),
    }
    return Response(data)
