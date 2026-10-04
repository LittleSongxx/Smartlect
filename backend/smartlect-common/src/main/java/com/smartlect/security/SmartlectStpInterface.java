package com.smartlect.security;

import cn.dev33.satoken.session.SaSession;
import cn.dev33.satoken.stp.StpInterface;
import com.smartlect.component.RedisComponent;
import com.smartlect.entity.dto.AdminPrincipalDTO;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * Sa-Token 权限数据源：@SaCheckPermission 的校验走这里。
 * admin loginType 从 Sa-Token session 的 dataMap.adminPrincipal 加载权限码与角色，
 * 与登录时 AccountController 存入的 AdminPrincipalDTO 保持一致。
 */
@Component
public class SmartlectStpInterface implements StpInterface {

    @Resource
    private RedisComponent redisComponent;

    @Override
    public List<String> getPermissionList(Object loginId, String loginType) {
        if (!StpAdminLogic.LOGIN_TYPE.equals(loginType)) {
            return List.of();
        }
        AdminPrincipalDTO principal = loadAdminPrincipal(String.valueOf(loginId));
        return principal == null ? List.of() : new ArrayList<>(principal.getPermissions());
    }

    @Override
    public List<String> getRoleList(Object loginId, String loginType) {
        if (!StpAdminLogic.LOGIN_TYPE.equals(loginType)) {
            return List.of();
        }
        AdminPrincipalDTO principal = loadAdminPrincipal(String.valueOf(loginId));
        return principal == null ? List.of() : new ArrayList<>(principal.getRoles());
    }

    private AdminPrincipalDTO loadAdminPrincipal(String adminId) {
        try {
            SaSession session = StpAdminLogic.LOGIC.getSessionByLoginId(adminId, false);
            if (session == null) {
                return null;
            }
            Object principal = session.get("adminPrincipal");
            return principal instanceof AdminPrincipalDTO dto ? dto : null;
        } catch (Exception e) {
            return null;
        }
    }
}
