package com.smartlect.security;

import com.smartlect.constants.TrialIdentities;
import com.smartlect.entity.po.OrderComment;
import com.smartlect.entity.po.OrderInfo;
import com.smartlect.entity.po.OrderItem;
import com.smartlect.entity.vo.PaginationResultVO;

import java.util.Collection;

public final class TrialOrderPrivacy {

    private static final String MASKED_BUYER = "作品集买家";

    private TrialOrderPrivacy() {
    }

    public static boolean active() {
        return TrialIdentities.isTrialAdmin(AdminSecurityContext.current());
    }

    public static <T> T redact(T payload) {
        if (!active() || payload == null) {
            return payload;
        }
        if (payload instanceof PaginationResultVO<?> page) {
            redactAll(page.getList());
            return payload;
        }
        if (payload instanceof Collection<?> items) {
            redactAll(items);
            return payload;
        }
        redactOne(payload);
        return payload;
    }

    private static void redactAll(Collection<?> items) {
        if (items == null) {
            return;
        }
        for (Object item : items) {
            redactOne(item);
        }
    }

    private static void redactOne(Object item) {
        if (item instanceof OrderInfo order) {
            order.setUserId(null);
            order.setNickName(MASKED_BUYER);
            order.setAvatar(null);
            if (order.getOrderItemList() != null) {
                for (OrderItem line : order.getOrderItemList()) {
                    line.setRemark(null);
                }
            }
            return;
        }
        if (item instanceof OrderComment comment) {
            comment.setUserId(null);
            comment.setNickName(MASKED_BUYER);
            comment.setAvatar(null);
        }
    }
}
