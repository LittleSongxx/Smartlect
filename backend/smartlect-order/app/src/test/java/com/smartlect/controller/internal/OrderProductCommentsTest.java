package com.smartlect.controller.internal;

import com.smartlect.biz.OrderCommentService;
import com.smartlect.entity.po.OrderComment;
import com.smartlect.entity.query.OrderCommentQuery;
import com.smartlect.entity.vo.ResponseVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class OrderProductCommentsTest {
    private final OrderCommerceInternalController controller = new OrderCommerceInternalController();
    private final OrderCommentService service = mock(OrderCommentService.class);

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(controller, "orderCommentService", service);
    }

    private OrderComment comment(String productId, Integer star, String content) {
        OrderComment c = new OrderComment();
        c.setOrderId("o-1");
        c.setProductId(productId);
        c.setStar(star);
        c.setCommentContent(content);
        c.setNickName("买家");
        return c;
    }

    @Test
    void productCommentsReturnsScoredCommentsAndSkipsIncompleteOnes() {
        when(service.findListByParam(any())).thenReturn(java.util.Arrays.asList(
                comment("p1", 5, "很好用"),
                comment("p1", 2, "一般般"),
                comment("p1", null, "没有星级")));

        ResponseVO<List<Map<String, Object>>> response =
                controller.productComments(Map.of("productId", "p1", "limit", 10));

        assertEquals(2, response.getData().size());
        assertEquals(5, response.getData().get(0).get("star"));
        assertNull(response.getData().get(0).get("recommentContent"));

        ArgumentCaptor<OrderCommentQuery> captor = ArgumentCaptor.forClass(OrderCommentQuery.class);
        verify(service).findListByParam(captor.capture());
        assertEquals("p1", captor.getValue().getProductId());
        assertEquals(10, captor.getValue().getSimplePage().getEnd());
        // The sort fragment and the page window are raw SQL text: assert them literally, a
        // camelCase column or an offset would only fail in MySQL, not in this unit test.
        assertEquals("o.comment_time desc", captor.getValue().getOrderBy().toString());
        assertEquals(0, captor.getValue().getSimplePage().getStart());
        // Soft-deleted and pending-image-review rows must not reach the analysis.
        assertEquals(0, captor.getValue().getStatus());
    }

    @Test
    void emptyProductIdReturnsEmptyListWithoutQuery() {
        ResponseVO<List<Map<String, Object>>> response = controller.productComments(Map.of());
        assertTrue(response.getData().isEmpty());
        verifyNoInteractions(service);
    }
}
