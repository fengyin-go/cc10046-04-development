"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import source_attribution
from app.routers import resource
from app.routers import chains

# 来源归属专属路由必须先于通用资源路由注册，否则 /api/attributions/...
# 会被通用的 /api/{module}/{entry_id} 抢先匹配。
ROUTERS = [source_attribution, resource, chains]
