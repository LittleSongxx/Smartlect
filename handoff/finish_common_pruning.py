from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'backend'
common = root / 'smartlect-common/src'
path = common / 'test/java/com/smartlect/interceptor/AdminRbacMatrixTest.java'
s = path.read_text()
s = re.sub(r'                Map.entry\("(aiConfig|aiEvaluate|aiPilot|supportRead|supportWrite)".*?\n', '', s)
s = re.sub(r'        roles.put\("(AI_OPERATOR|SUPPORT_AGENT)".*?;\n', '', s, flags=re.S)
s = re.sub(r'        @RequireAdminPermission\(AdminPermissions.(AI_CONFIG|AI_EVALUATE|AI_PILOT|SUPPORT_READ|SUPPORT_WRITE)\)\n        void \w+\(\) \{\n        }\n\n', '', s)
s = s.replace('handler("aiConfig")','handler("manage")').replace('supportOrAudit','manageOrAudit').replace('AdminPermissions.SUPPORT_READ','AdminPermissions.ADMIN_MANAGE').replace('fiveRolesEnforce','commerceRolesEnforce')
path.write_text(s)

# No retained caller needs the old conversational-image special case. Generic
# avatar/comment preparation, validation and moderation remain intact.
path = common / 'main/java/com/smartlect/utils/ImageCompressUtils.java'
s = path.read_text()
a = s.index('    /** Normalize Agent images')
b = s.index('    private static boolean needsTranscodeToJpeg', a)
path.write_text(s[:a] + s[b:])

for module in ('smartlect-common','smartlect-order','smartlect-coupon'):
    for path in (root/module).rglob('*'):
        if path.is_file() and path.suffix in ('.java','.sql') and 'target' not in path.parts:
            s = path.read_text().replace('Agent worker', 'trusted growth service').replace('Python Agent', 'Python growth service').replace('Agent', 'Growth')
            s = s.replace('allGrowthWriteRoutes', 'allCommerceWriteRoutes')
            path.write_text(s)
print('Removed obsolete AI permissions and image branch; retained RBAC checks')
