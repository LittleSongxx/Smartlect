package com.smartlect.biz.impl;

import com.smartlect.api.dto.*;
import com.smartlect.api.enums.*;
import com.smartlect.api.support.*;
import com.smartlect.api.vo.*;
import com.smartlect.biz.CouponRushOrderService;
import com.smartlect.biz.OrderInfoService;
import com.smartlect.biz.OrderQuoteService;
import com.smartlect.biz.OrderRequestIdempotencyService;
import com.smartlect.biz.RefundSagaService;
import com.smartlect.component.OrderNotificationPublisher;
import com.smartlect.component.RedisComponent;
import com.smartlect.component.PayOrderRedisComponent;
import com.smartlect.component.RemoteCompensateRecorder;
import com.smartlect.constants.Constants;
import com.smartlect.constants.RabbitMQConfig;
import com.smartlect.constants.ReliableMessageSender;
import com.smartlect.constants.TransactionalMqSender;
import com.smartlect.entity.config.AppConfig;
import com.smartlect.entity.dto.LogisticsSendDTO;
import com.smartlect.entity.enums.MessageReliabilityLevelEnum;
import com.smartlect.entity.enums.PageSize;
import com.smartlect.entity.enums.ResponseCodeEnum;
import com.smartlect.entity.po.*;
import com.smartlect.entity.query.*;
import com.smartlect.entity.vo.PaginationResultVO;
import com.smartlect.exception.BusinessException;
import com.smartlect.state.OrderStateEvent;
import com.smartlect.state.OrderStateMachine;
import com.smartlect.exception.PayOrderLifecycleBusyException;
import com.smartlect.mappers.OrderCouponRelMapper;
import com.smartlect.mappers.OrderInfoMapper;
import com.smartlect.mappers.OrderItemMapper;
import com.smartlect.mappers.OrderLogisticsInfoMapper;
import com.smartlect.integration.CommerceOutcomeClient;
import com.smartlect.support.MqIdempotencyKeys;
import com.smartlect.utils.OrderListPayAmountHelper;
import com.smartlect.utils.OrderPayAmountUtil;
import com.smartlect.utils.StringTools;
import io.seata.spring.annotation.GlobalTransactional;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;
import java.util.stream.Collectors;

@Service("orderInfoService")
@Slf4j
public class OrderInfoServiceImpl implements OrderInfoService {

	@Resource
	private OrderInfoMapper<OrderInfo, OrderInfoQuery> orderInfoMapper;

	@Resource
	private OrderStateMachine orderStateMachine;

	@Resource
	private StockFeignSupport stockFeignSupport;

	@Resource
	private ProductFeignSupport productFeignSupport;

	@Resource
	private UserFeignSupport userFeignSupport;

	@Resource
	private CouponFeignSupport couponFeignSupport;

	@Resource
	private OrderItemMapper<OrderItem, OrderItemQuery> orderItemMapper;

	@Resource
	private CartFeignSupport cartFeignSupport;
    @Autowired
    private RedisComponent redisComponent;
    @Resource
    private PayOrderRedisComponent payOrderRedisComponent;
    @Autowired
    private AppConfig appConfig;

	@Resource
	private OrderCouponRelMapper<OrderCouponRel, OrderCouponRelQuery> orderCouponRelMapper;

	@Resource
	private OrderLogisticsInfoMapper<OrderLogisticsInfo, OrderLogisticsInfoQuery> orderLogisticsInfoMapper;

	@Resource
	private PayFeignSupport payFeignSupport;
	@Resource
	private RefundSagaService refundSagaService;

	@Resource
	private ReliableMessageSender reliableMessageSender;
	@Resource
	private TransactionalMqSender transactionalMqSender;
	@Resource
	private RemoteCompensateRecorder remoteCompensateRecorder;
	@Resource
	private OrderRequestIdempotencyService orderRequestIdempotencyService;
	@Resource
	private OrderQuoteService orderQuoteService;
	@Resource
	private CouponRushOrderService couponRushOrderService;
	@Resource
	private CommerceOutcomeClient commerceOutcomeClient;
	@Resource
	private com.smartlect.biz.OrderAttributionService orderAttributionService;
	@Resource
	private OrderNotificationPublisher orderNotificationPublisher;

	@Override
	public List<OrderInfo> findListByParam(OrderInfoQuery param) {
		List<OrderInfo> list = this.orderInfoMapper.selectList(param);
		if (list != null && !list.isEmpty()) {
			if (Boolean.TRUE.equals(param.isQueryItems())) {
				enrichCouponInfo(list);
			}
			if (Boolean.TRUE.equals(param.getQueryUser())) {
				enrichUserBrief(list);
			}
		}
		return list;
	}

	@Override
	public Integer findCountByParam(OrderInfoQuery param) {
		return this.orderInfoMapper.selectCount(param);
	}

	@Override
	public PaginationResultVO<OrderInfo> findListByPage(OrderInfoQuery param) {
		int count = this.findCountByParam(param);
		int pageSize = param.getPageSize() == null ? PageSize.SIZE15.getSize() : param.getPageSize();

		SimplePage page = new SimplePage(param.getPageNo(), count, pageSize);
		param.setSimplePage(page);
		List<OrderInfo> list = this.findListByParam(param);
		PaginationResultVO<OrderInfo> result = new PaginationResultVO(count, pageSize, page.getPageNo(), page.getPageTotal(), list);
		return result;
	}

	@Override
	public Integer add(OrderInfo bean) {
		return this.orderInfoMapper.insert(bean);
	}

	@Override
	public Integer addBatch(List<OrderInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderInfoMapper.insertBatch(listBean);
	}

	@Override
	public Integer addOrUpdateBatch(List<OrderInfo> listBean) {
		if (listBean == null || listBean.isEmpty()) {
			return 0;
		}
		return this.orderInfoMapper.insertOrUpdateBatch(listBean);
	}

	@Override
	public Integer updateByParam(OrderInfo bean, OrderInfoQuery param) {
		StringTools.checkParam(param);
		return this.orderInfoMapper.updateByParam(bean, param);
	}

	@Override
	public Integer deleteByParam(OrderInfoQuery param) {
		StringTools.checkParam(param);
		return this.orderInfoMapper.deleteByParam(param);
	}

	@Override
	public OrderInfo getOrderInfoByOrderId(String orderId) {
		return this.orderInfoMapper.selectByOrderId(orderId);
	}

	@Override
	public Integer updateOrderInfoByOrderId(OrderInfo bean, String orderId) {
		return this.orderInfoMapper.updateByOrderId(bean, orderId);
	}

	@Override
	public Integer deleteOrderInfoByOrderId(String orderId) {
		return this.orderInfoMapper.deleteByOrderId(orderId);
	}

	@Override
	@GlobalTransactional(name = "smartlect-post-order", rollbackFor = Exception.class)
	@Transactional(rollbackFor = Exception.class)
	public PayInfoDTO postOrder(String userId, PostOrderDTO postOrderDTO, String idempotencyKey) {
		return orderRequestIdempotencyService.execute(
				userId,
				OrderRequestIdempotencyService.COMMAND_POST_ORDER,
				idempotencyKey,
				postOrderDTO,
				PayInfoDTO.class,
				() -> createOrder(userId, postOrderDTO));
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public Map<String, Object> quoteOrder(String userId, PostOrderDTO request) {
		PreparedOrder prepared = prepareOrder(userId, request);
		if (!StringTools.isEmpty(request.getUserCouponId())) {
			BigDecimal gross = prepared.orders().stream().map(OrderInfo::getAmount)
					.reduce(BigDecimal.ZERO, BigDecimal::add);
			CouponLockResultVO coupon = couponFeignSupport.preview(userId, request.getUserCouponId(), gross);
			if (coupon.getDiscountAmount() != null && coupon.getDiscountAmount().signum() > 0) {
				distributeCouponDiscount(prepared.orders(), coupon.getDiscountAmount());
				OrderListPayAmountHelper.ensureOrderListMinTotalPay(prepared.orders());
			}
		}
		return orderQuoteService.issue(userId, request, prepared.address(), prepared.items(), total(prepared.orders()));
	}

	@Override
	@GlobalTransactional(name = "smartlect-confirmed-order", rollbackFor = Exception.class)
	@Transactional(rollbackFor = Exception.class)
	public PayInfoDTO createConfirmed(String userId, PostOrderDTO request, String quoteId,
			Long confirmedAmountCents, String idempotencyKey) {
		return createConfirmed(userId, request, quoteId, confirmedAmountCents, idempotencyKey, null);
	}

	@Override
	@GlobalTransactional(name = "smartlect-confirmed-order", rollbackFor = Exception.class)
	@Transactional(rollbackFor = Exception.class)
	public PayInfoDTO createConfirmed(String userId, PostOrderDTO request, String quoteId,
			Long confirmedAmountCents, String idempotencyKey, String attributionContextToken) {
		if (quoteId == null || confirmedAmountCents == null) OrderQuoteService.reconfirm();
		// Idempotency precedes quote expiry/consumption checks and all remote business reads.
		return orderRequestIdempotencyService.execute(userId,
				OrderRequestIdempotencyService.COMMAND_POST_ORDER_V2, idempotencyKey,
				Map.of("quoteId", quoteId, "confirmedAmountCents", confirmedAmountCents,
						"order", OrderQuoteService.input(request)), PayInfoDTO.class, () -> {
			OrderQuoteService.Quote quote = orderQuoteService.lock(userId, quoteId);
			orderQuoteService.validateRequest(quote, userId, request, confirmedAmountCents);
			PayInfoDTO response = createOrder(userId, request, quote, confirmedAmountCents, attributionContextToken);
			orderQuoteService.consume(quote, response.getPayOrderId());
			return response;
		});
	}

	private record PreparedOrder(PayChannelEnum channel, OrderFromTypeEnum from, UserAddressVO address,
			List<ProductItem> products, List<OrderInfo> orders, List<OrderItem> items,
			List<CartDeleteItemDTO> cart, List<OrderLogisticsInfo> logistics, String subject,
			String payOrderId, Date now) { }

	private PreparedOrder prepareOrder(String userId, PostOrderDTO postOrderDTO) {
		PayChannelEnum payChannelEnum = PayChannelEnum.getByPayScene(postOrderDTO.getPayMethod());
		if (payChannelEnum == null) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}

		OrderFromTypeEnum orderFromTypeEnum = OrderFromTypeEnum.getByType(postOrderDTO.getOrderFrom());
		if (orderFromTypeEnum == null) {
			throw new BusinessException(ResponseCodeEnum.CODE_600);
		}

		// PostOrderDTO中的数据有：订单列表(商品Id，商品属性Ids，购买数量，备注)，支付方式，地址ID，订单来源
		// 存入order_info表的数据有：订单Id，数量，用户Id，创建订单时间，订单状态，支付渠道，支付场景，支付订单Id，渠道订单Id，评价状态
		// 存入order_item表数据有：订单明细Id，订单Id，封面图，商品Id，商品名称，商品属性IdHash，property_info,item总价格，购买数量，订单明细状态，备注，refund_order_id
		// 同一个商品id的放在同一个订单中，分为不同的订单明细，同一个商品属性id的放在同一个订单明细中
		// 根据addressId获取地址信息
		// 根据addressId获取地址信息（user 服务）
		UserAddressVO userAddress = userFeignSupport.getAddress(postOrderDTO.getAddressId(), userId);
		// 若地址不存在则抛出异常
		if (userAddress == null || StringTools.isEmpty(userAddress.getAddress())) {
			throw new BusinessException("当前地址不存在");
		}

		List<ProductItem> orderList = postOrderDTO.getOrderList();
		List<String> productIdList = orderList.stream().map(ProductItem::getProductId).collect(Collectors.toList());
        // 遍历orderList
		// 创建Map：productId -> OrderInfo；productId -> OrderItem
		Map<String, OrderInfo> productIdOrderInfoMap = new HashMap<>();
		Map<String, OrderItem> productIdOrderItemMap = new HashMap<>();
		Map<String, Integer> productItemCountMap = new HashMap<>();
		ProductSnapshotBatchVO snapshot = productFeignSupport.snapshotBatch(productIdList);
		Map<String, ProductInfoSnapshotVO> productInfoMap = productFeignSupport.toProductInfoMap(snapshot);
		Map<String, ProductPropertyValueSnapshotVO> productPropertyValueMap = productFeignSupport.toPropertyValueMap(snapshot);
		Map<String, ProductSkuSnapshotVO> productSkuMap = productFeignSupport.toSkuMapByPropertyValueIds(snapshot);
		// 获取当前时间
		Date now = new Date();
		List<ProductItem> newList = new ArrayList<>();
		List<OrderItem> orderItemList = new ArrayList<>();
		// 购物车列表
		List<CartDeleteItemDTO> productCartList = new ArrayList<>();
		// 物流信息
		List<OrderLogisticsInfo> orderLogisticsInfoList = new ArrayList<>();
		LogisticsSendDTO logisticsSendDTO = redisComponent.getLogisticsInfo();
		String unifiedPayOrderId = StringTools.createPayOrderId();
		for (ProductItem productItem : orderList) {
			// 根据productId获取productInfoMap中的productInfo
			ProductInfoSnapshotVO productInfo = productInfoMap.get(productItem.getProductId());
			// 根据productId+productPropertyValueId获取productPropertyValueMap中的productPropertyValue
			// 遍历每个属性值ID，分别查询
			String[] propertyValueIdArray = productItem.getPropertyValueIds().split("-");
			List<ProductPropertyValueSnapshotVO> propertyValueList = new ArrayList<>();
			for (String propertyValueId : propertyValueIdArray) {
				ProductPropertyValueSnapshotVO pv = productPropertyValueMap.get(productItem.getProductId() + propertyValueId);
				if (pv != null) {
					propertyValueList.add(pv);
				}
			}
			// 根据productId+productPropertyValueIds获取productSkuMap中的productSku
			ProductSkuSnapshotVO productSku = productSkuMap.get(productItem.getProductId() + productItem.getPropertyValueIds());
			// 先判断productInfo,productPropertyValue,productSku是否存在
			if (productInfo == null || !ProductStatusEnum.ON_SALE.getStatus().equals(productInfo.getStatus())) {
				throw new BusinessException("商品不存在或已下架");
			}
			if (propertyValueList.isEmpty()) {
				throw new BusinessException("商品属性不存在");
			}
			if (productSku == null) {
				throw new BusinessException("商品sku不存在");
			}
			if (productItem.getBuyCount() == null || productItem.getBuyCount() < 1
					|| productItem.getBuyCount() > Constants.ORDER_MAX_BUY_COUNT_PER_SKU) {
				throw new BusinessException("单件商品购买数量为 1~" + Constants.ORDER_MAX_BUY_COUNT_PER_SKU + " 件");
			}
			// 判断库存（真相源：smartlect_stock）
			productItem.setPropertyValueIdHash(productSku.getPropertyValueIdHash());
			int available = stockFeignSupport.getAvailable(productItem.getProductId(), productItem.getPropertyValueIdHash());
			if (available < productItem.getBuyCount()) {
				throw new BusinessException("商品【" + productInfo.getProductName() + "】库存不足");
			}

			OrderInfo orderInfo = new OrderInfo();
			// 检查当前productId的商品是否已经加入过订单，通过Map<productId,OrderInfo>
			// 新建一个OrderItem
			OrderItem orderItem = new OrderItem();
			// 若没有则新生成一个订单
			if (!productIdOrderInfoMap.containsKey(productItem.getProductId())) {
				// 将productItem中的数据赋给orderInfo
				orderInfo.setOrderId(StringTools.createOrderId());
				// 先将amount总金额设置为0.0
				orderInfo.setAmount(new BigDecimal(Constants.ZERO_STR));
				orderInfo.setUserId(userId);
				orderInfo.setOrderTime(now);
				// 订单状态为待付款
				orderInfo.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
				// 评论状态为未评论
				orderInfo.setCommentStatus(CommentStatusEnum.NORMAL.getStatus());
				orderInfo.setPayChannel(postOrderDTO.getPayMethod());
				orderInfo.setPayScene(postOrderDTO.getOrderFrom().toString());
				orderInfo.setPayOrderId(unifiedPayOrderId);
				orderInfo.setOrderItemList(new ArrayList<>());
				// 记录地址信息
				OrderLogisticsInfo orderLogisticsInfo = new OrderLogisticsInfo();
				orderLogisticsInfo.setOrderId(orderInfo.getOrderId());
				orderLogisticsInfo.setUserId(userId);
				orderLogisticsInfo.setReceiverName(userAddress.getAddressee());
				orderLogisticsInfo.setReceiverPhone(userAddress.getPhone());
				orderLogisticsInfo.setReceiverAddress(userAddress.getAddress());
				orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.PENDING_SHIPMENT.getStatus());
				// 设置默认发货信息:发货人、发货电话、发货地
				if (logisticsSendDTO != null) {
					orderLogisticsInfo.setSenderName(logisticsSendDTO.getSenderName());
					orderLogisticsInfo.setSenderPhone(logisticsSendDTO.getSenderPhone());
					orderLogisticsInfo.setSenderAddress(logisticsSendDTO.getSenderAddress());
				}
				orderLogisticsInfoList.add(orderLogisticsInfo);
				// 将orderInfo加入到Map
				productIdOrderInfoMap.put(productItem.getProductId(), orderInfo);
			} else {
				orderInfo = productIdOrderInfoMap.get(productItem.getProductId());
			}
			// 为orderItem填充属性
			orderItem.setOrderId(orderInfo.getOrderId());
			// 获取当前商品的订单项序号
			Integer itemCount = productItemCountMap.getOrDefault(productItem.getProductId(), 0) + 1;
			productItemCountMap.put(productItem.getProductId(), itemCount);
			// 填充orderItemId，为orderId加上当前的商品数量，即为同一个productId的第几个商品
			orderItem.setOrderItemId(orderInfo.getOrderId() + "_" + itemCount);
			// 填充productId、productName、property_value_id_hash
			orderItem.setProductId(productItem.getProductId());
			orderItem.setProductName(productInfo.getProductName());
			orderItem.setPropertyValueIdHash(productSku.getPropertyValueIdHash());
			// 组装属性信息：属性名称:属性值;属性名称:属性值
			List<String> propertyData = new ArrayList<>();
			for (String propertyValueId : propertyValueIdArray) {
				ProductPropertyValueSnapshotVO productPropertyValue = productPropertyValueMap.get(productItem.getProductId() + propertyValueId);
				if (productPropertyValue != null) {
					propertyData.add(productPropertyValue.getPropertyName() + ":" + productPropertyValue.getPropertyValue());
				}
			}
			orderItem.setPropertyInfo(String.join(";", propertyData));
			orderItem.setBuyCount(productItem.getBuyCount());
			orderItem.setItemAmount(productSku.getPrice().multiply(new BigDecimal(productItem.getBuyCount())));
			orderItem.setOrderItemStatus(OrderItemStatusEnum.NORMAL.getStatus());
			orderItem.setRemark(productItem.getRemark());
			orderItem.setRefundOrderId(null);
			orderItem.setRecommendationRequestId(productItem.getRecommendationRequestId());
			orderItem.setRecommendationPosition(productItem.getRecommendationPosition());
			orderItem.setRecommendationSource(productItem.getRecommendationSource());
			orderItem.setRecommendationAttributedAt(productItem.getRecommendationAttributedAt());
			String cover = null;
			// 优先取 propertyValue 中的 cover
			for (ProductPropertyValueSnapshotVO pv : propertyValueList) {
				if (!StringTools.isEmpty(pv.getPropertyCover())) {
					cover = pv.getPropertyCover();
					break;
				}
			}
			// 如果 propertyValue 中没有 cover，则取 productInfo 中的 cover
			if (StringTools.isEmpty(cover)) {
				cover = productInfo.getCover();
				if (!StringTools.isEmpty(cover) && cover.contains(",")) {
					cover = cover.split(",")[0];
				}
			}
			orderItem.setCover(cover);
			productIdOrderItemMap.put(productItem.getProductId(), orderItem);
			orderInfo.setAmount(orderInfo.getAmount().add(orderItem.getItemAmount()));
			orderInfo.getOrderItemList().add(orderItem);
			orderItemList.add(orderItem);
			newList.add(productItem);
			// 如果是在购物车提交的订单，记录商品购物车信息
			if (OrderFromTypeEnum.CART == orderFromTypeEnum) {
				productCartList.add(new CartDeleteItemDTO(
						userId,
						productItem.getProductId(),
						productSku.getPropertyValueIdHash(),
						productSku.getPropertyValueIds()));
			}
		}
		String subject;
		if (OrderFromTypeEnum.CART == orderFromTypeEnum) {
			subject = String.format(Constants.CART_PAY_NAME, orderItemList.size());
		} else {
			// 直接从第一个 ProductItem 获取名称，或者从 orderItemList 获取
			subject = orderItemList.get(0).getProductName();
		}
		// 将productIdOrderInfoMap中的订单添加到orderInfoList
        List<OrderInfo> orderInfoList = new ArrayList<>(productIdOrderInfoMap.values());
		// 设置订单标题
		for(OrderInfo orderInfo : orderInfoList){
			orderInfo.setSubject(subject);
		}

		return new PreparedOrder(payChannelEnum, orderFromTypeEnum, userAddress, newList,
				orderInfoList, orderItemList, productCartList, orderLogisticsInfoList, subject, unifiedPayOrderId, now);
	}

	private static BigDecimal total(List<OrderInfo> orders) {
		return OrderPayAmountUtil.normalizeChannelPayAmount(orders.stream().map(OrderInfo::getAmount)
				.reduce(BigDecimal.ZERO, BigDecimal::add));
	}

	private PayInfoDTO createOrder(String userId, PostOrderDTO request) {
		return createOrder(userId, request, null, null);
	}

	private PayInfoDTO createOrder(String userId, PostOrderDTO postOrderDTO,
			OrderQuoteService.Quote quote, Long confirmedAmountCents) {
		return createOrder(userId, postOrderDTO, quote, confirmedAmountCents, null);
	}

	private PayInfoDTO createOrder(String userId, PostOrderDTO postOrderDTO,
			OrderQuoteService.Quote quote, Long confirmedAmountCents, String attributionContextToken) {
		PreparedOrder prepared = prepareOrder(userId, postOrderDTO);
		PayChannelEnum payChannelEnum = prepared.channel();
		OrderFromTypeEnum orderFromTypeEnum = prepared.from();
		List<ProductItem> newList = prepared.products();
		List<OrderInfo> orderInfoList = prepared.orders();
		List<OrderItem> orderItemList = prepared.items();
		List<CartDeleteItemDTO> productCartList = prepared.cart();
		List<OrderLogisticsInfo> orderLogisticsInfoList = prepared.logistics();
		String subject = prepared.subject();
		String unifiedPayOrderId = prepared.payOrderId();
		Date now = prepared.now();
		OrderCouponRel couponRel = null;
		// --- 下单使用优惠券（可选）：经 coupon 服务校验并预占 ---
		String userCouponId = postOrderDTO.getUserCouponId();
		boolean couponLocked = false;
		if (!StringTools.isEmpty(userCouponId)) {
			BigDecimal orderAmountBeforeDiscount = orderInfoList.stream()
					.map(OrderInfo::getAmount)
					.reduce(BigDecimal.ZERO, BigDecimal::add);
			CouponLockResultVO lockResult = couponFeignSupport.validateAndLock(userId, userCouponId, orderAmountBeforeDiscount);
			if (Boolean.TRUE.equals(lockResult.getLocked()) && lockResult.getDiscountAmount() != null
					&& lockResult.getDiscountAmount().compareTo(BigDecimal.ZERO) > 0) {
				distributeCouponDiscount(orderInfoList, lockResult.getDiscountAmount());
				OrderListPayAmountHelper.ensureOrderListMinTotalPay(orderInfoList);

				OrderCouponRel rel = new OrderCouponRel();
				rel.setOrderId(orderInfoList.get(0).getOrderId());
				rel.setUserCouponId(userCouponId);
				rel.setCouponId(lockResult.getCouponId());
				rel.setDiscountAmount(lockResult.getDiscountAmount());
				rel.setCreateTime(now);
				couponRel = rel;
				couponLocked = true;
			}
		}
		// 统一操作数据库
		if (newList.isEmpty()) {
			throw new BusinessException("请选择商品");
		}
		boolean stockDeducted = false;
		boolean stockLocked = false;
		List<ProductItem> deductList = copyItemsWithSignedBuyCount(newList, true);
		try {
			stockFeignSupport.lockAndVerify(newList);
			stockLocked = true;
			// Compare the exact final amount and resolved SKU/address after coupon/stock locks,
			// before any order, coupon relation or payment-intent persistence.
			if (quote != null) {
				orderQuoteService.validate(quote, userId, postOrderDTO, confirmedAmountCents,
						prepared.address(), orderItemList, total(orderInfoList));
			}
			if (couponRel != null) orderCouponRelMapper.insert(couponRel);
			// 插入数据库
			orderInfoMapper.insertBatch(orderInfoList);
			orderItemMapper.insertBatch(orderItemList);
			orderLogisticsInfoMapper.insertBatch(orderLogisticsInfoList);
			orderAttributionService.freeze(userId, orderInfoList, attributionContextToken);
			// 远程扣减库存（与本地订单事务分离；后续步骤失败时补偿回补）
			stockFeignSupport.changeStockBatch(deductList, "order-deduct:" + unifiedPayOrderId);
			stockDeducted = true;
			if (OrderFromTypeEnum.CART == orderFromTypeEnum) {
				cartFeignSupport.deleteBatch(productCartList);
			}
			BigDecimal totalAmount = orderInfoList.stream().map(OrderInfo::getAmount).reduce(BigDecimal.ZERO, BigDecimal::add);
			totalAmount = OrderPayAmountUtil.normalizeChannelPayAmount(totalAmount);

			log.info("提交订单,payOrderId={}, 订单数量={}, 总金额={}", unifiedPayOrderId, orderInfoList.size(), totalAmount);

			payFeignSupport.createPending(userId, unifiedPayOrderId, orderInfoList.get(0).getOrderId(),
					totalAmount, postOrderDTO.getPayMethod());
			PayInfoDTO payInfoDTO = requestInitialPayInfoBestEffort(
					payChannelEnum.getPayScene(), unifiedPayOrderId, subject, totalAmount);

			for (OrderInfo orderInfo : orderInfoList) {
				PayOrderMessageDTO dto = new PayOrderMessageDTO();
				dto.setOrderId(orderInfo.getOrderId());
				transactionalMqSender.sendAfterCommit(
						RabbitMQConfig.PAY_EXCHANGE,
						RabbitMQConfig.PAY_TIMEOUT_DELAY_KEY,
						dto,
						MqIdempotencyKeys.payTimeout(orderInfo.getOrderId()),
						MessageReliabilityLevelEnum.STANDARD);
			}
			return payInfoDTO;
		} catch (RuntimeException ex) {
			if (stockDeducted) {
				try {
					stockFeignSupport.restoreOrderStock(
							unifiedPayOrderId, copyItemsWithSignedBuyCount(newList, false));
				} catch (Exception compensateEx) {
					log.error("下单失败后库存回补失败, payOrderId={}", unifiedPayOrderId, compensateEx);
					remoteCompensateRecorder.recordStockChangeBatch(
							unifiedPayOrderId, copyItemsWithSignedBuyCount(newList, false), compensateEx);
				}
			} else if (stockLocked) {
				// lockAndVerify succeeded but deduct was not confirmed. Persist an explicit
				// outbox of the intended deduct so ops can reconcile; do not invent a restore.
				log.error("先锁后扣中间失败, payOrderId={}", unifiedPayOrderId, ex);
				remoteCompensateRecorder.recordStockChangeBatch(unifiedPayOrderId, deductList, ex);
			}
			if (couponLocked) {
				try {
					couponFeignSupport.changeUserCouponStatus(userCouponId, userId,
							UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(), null);
				} catch (Exception compensateEx) {
					log.error("下单失败后优惠券解锁失败, payOrderId={}, userCouponId={}",
							unifiedPayOrderId, userCouponId, compensateEx);
					remoteCompensateRecorder.recordCouponUnlock(
							unifiedPayOrderId, userCouponId, userId,
							UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(),
							compensateEx);
				}
			}
			throw ex;
		}
	}

	PayInfoDTO requestInitialPayInfoBestEffort(
			String payScene, String payOrderId, String subject, BigDecimal amount) {
		if (OrderPayAmountUtil.isFreeOrder(amount)) {
			return new PayInfoDTO("FREE", payOrderId, BigDecimal.ZERO.setScale(2));
		}
		try {
			return payFeignSupport.getPayUrl(payScene, payOrderId, subject, amount);
		} catch (RuntimeException ex) {
			log.warn(
					"支付表单暂不可用，订单保持待支付并允许支付页重试, payOrderId={}, error={}",
					payOrderId,
					ex.getMessage());
			return new PayInfoDTO(null, payOrderId, amount);
		}
	}

	// 秒杀下单的校验/预占/建单/支付全在 CouponRushOrderServiceImpl，这里只保留接口契约的委托。
	@Override
	public CouponRushPrepareDTO prepareCouponRush(
			String userId, String couponId, String idempotencyKey) {
		return couponRushOrderService.prepareCouponRush(userId, couponId, idempotencyKey);
	}

	@Override
	public PayInfoDTO postCouponRushOrder(
			String userId, String couponId, String payMethod, String idempotencyKey) {
		return couponRushOrderService.postCouponRushOrder(userId, couponId, payMethod, idempotencyKey);
	}

	private void distributeCouponDiscount(List<OrderInfo> orderInfoList, BigDecimal discount) {
		BigDecimal remaining = discount;
		for (OrderInfo order : orderInfoList) {
			if (remaining.compareTo(BigDecimal.ZERO) <= 0) {
				break;
			}
			BigDecimal amt = order.getAmount() == null ? BigDecimal.ZERO : order.getAmount();
			BigDecimal off = remaining.min(amt);
			order.setAmount(amt.subtract(off).setScale(2, RoundingMode.HALF_UP));
			remaining = remaining.subtract(off);
		}
	}

	// 获取支付信息
	@Override
	public PayInfoDTO getPayInfo(String userId, String orderId) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			OrderInfoQuery payQuery = new OrderInfoQuery();
			payQuery.setPayOrderId(orderId);
			payQuery.setUserId(userId);
			List<OrderInfo> payOrders = orderInfoMapper.selectList(payQuery);
			if (!payOrders.isEmpty()) {
				orderInfo = payOrders.get(0);
			}
		}
		if (orderInfo == null || !orderInfo.getUserId().equals(userId)) {
			throw new BusinessException("订单不存在");
		}
		// 判断当前订单状态是否为待支付
		if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
			if (OrderStatusEnum.CLOSED.getStatus().equals(orderInfo.getOrderStatus())
					|| OrderStatusEnum.CANCELLED.getStatus().equals(orderInfo.getOrderStatus())) {
				throw new BusinessException("订单已关闭，请重新抢购");
			}
			throw new BusinessException("当前订单已支付");
		}
		PayChannelEnum payChannelEnum = resolveWaitPayChannel(orderInfo);
		String subject = orderInfo.getSubject();
		// 查询同一payOrderId下的所有订单,计算总金额
		OrderInfoQuery query = new OrderInfoQuery();
		query.setPayOrderId(orderInfo.getPayOrderId());
		List<OrderInfo> payOrderList = orderInfoMapper.selectList(query);
		BigDecimal amount = payOrderList.stream()
				.map(OrderInfo::getAmount)
				.reduce(BigDecimal.ZERO, BigDecimal::add);  // 累加所有订单金额
		amount = OrderPayAmountUtil.normalizeChannelPayAmount(amount);
		String payOrderId = orderInfo.getPayOrderId();

		PayInfoDTO payInfoDTO = payFeignSupport.getPayUrl(payChannelEnum.getPayScene(), payOrderId, subject, amount);
		// Alipay regenerates a channel trade here; mock uses one durable intent and must stay PENDING.
		if (payChannelEnum != PayChannelEnum.MOCK) {
			cancelOrder4Channel(orderInfo);
		}

		//更新支付订单ID
		OrderInfo updateOrderInfo = new OrderInfo();
		updateOrderInfo.setPayOrderId(payOrderId);
		orderInfoMapper.updateByOrderId(updateOrderInfo, orderInfo.getOrderId());
		return payInfoDTO;
	}

	// 取消订单
	// 从orderStatusEnum状态取消
	@Override
	@Transactional(rollbackFor = Exception.class)
	public void cancelOrder(String userId, String orderId, OrderStatusEnum orderStatusEnum) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			throw new BusinessException("订单不存在");
		}
		String payOrderId = orderInfo.getPayOrderId();
		if (StringTools.isEmpty(payOrderId)) {
			cancelOrderInLock(userId, orderId);
			return;
		}
		payOrderRedisComponent.runWithPayOrderLifecycleLock(payOrderId, () -> cancelOrderInLock(userId, orderId));
	}

	private void cancelOrderInLock(String userId, String orderId) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			throw new BusinessException("订单不存在");
		}
		if (userId != null && !orderInfo.getUserId().equals(userId)) {
			throw new BusinessException("订单不存在");
		}
		if (isCouponRushOrder(orderInfo)) {
			if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
				throw new BusinessException("当前订单状态不能取消");
			}
			cancelCouponRushOrder(orderId, userId);
			return;
		}
		if (userId == null && !StringTools.isEmpty(orderInfo.getPayOrderId())) {
			closeUnpaidPayOrderForTimeout(orderInfo.getPayOrderId());
			return;
		}
		if (!StringTools.isEmpty(orderInfo.getPayOrderId())) {
			cancelUnpaidPayOrderForUser(userId, orderInfo.getPayOrderId());
			return;
		}
		if (!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())) {
			throw new BusinessException("当前订单状态不能取消");
		}
		OrderStateEvent cancelEvent = userId != null ? OrderStateEvent.USER_CANCEL : OrderStateEvent.SYSTEM_CANCEL;
		int rows = orderStateMachine.transition(orderId, OrderStatusEnum.WAIT_PAYMENT, cancelEvent);
		if (rows == 0) {
			if (userId != null) {
				throw new BusinessException("当前订单状态不能取消");
			}
			return;
		}
		restoreStockForOrders(orderId, List.of(orderInfo));
		recordCancellationOutcomes(List.of(orderInfo), "USER_CANCEL", "CANCELLED");
	}

	private void cancelUnpaidPayOrderForUser(String userId, String payOrderId) {
		List<OrderInfo> orderList = loadOrdersByPayOrderId(payOrderId);
		if (orderList.isEmpty()
				|| orderList.stream().anyMatch(order -> !Objects.equals(userId, order.getUserId()))) {
			throw new BusinessException("订单不存在");
		}
		if (orderList.stream().anyMatch(order -> isPaidOrBeyond(order.getOrderStatus()))) {
			throw new BusinessException("当前支付单已支付无法取消");
		}
		if (orderList.stream().anyMatch(order ->
				!OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(order.getOrderStatus())
						&& !isClosedOrCancelled(order.getOrderStatus()))) {
			throw new BusinessException("当前支付单状态不能取消");
		}
		List<OrderInfo> waitingOrders = orderList.stream()
				.filter(order -> OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(order.getOrderStatus()))
				.toList();
		if (waitingOrders.isEmpty()) {
			return;
		}
		if (waitingOrders.size() != orderList.size()) {
			throw new BusinessException("支付单内子订单状态不一致，请联系客服处理");
		}

		int rows = orderStateMachine.transitionPayOrder(payOrderId, OrderStatusEnum.WAIT_PAYMENT,
				OrderStateEvent.USER_CANCEL);
		if (rows != waitingOrders.size()) {
			throw new BusinessException("支付单取消失败，子订单状态已变化");
		}

		markPayOrderClosedIfNeeded(payOrderId);
		payFeignSupport.markClosed(payOrderId);
		cancelOrder4Channel(waitingOrders.get(0));
		releaseCouponIfNeeded(payOrderId);
		restoreStockForOrders(payOrderId, waitingOrders);
		recordCancellationOutcomes(waitingOrders, "USER_CANCEL", "CANCELLED");
	}

	private boolean isPaidOrBeyond(Integer status) {
		if (status == null) {
			return false;
		}
		return OrderStatusEnum.PAID.getStatus().equals(status)
				|| OrderStatusEnum.SHIPPED.getStatus().equals(status)
				|| OrderStatusEnum.COMPLETED.getStatus().equals(status)
				|| OrderStatusEnum.REFUNDED.getStatus().equals(status)
				|| OrderStatusEnum.PARTIALLY_REFUNDED.getStatus().equals(status);
	}

	private void closeUnpaidPayOrderForTimeout(String payOrderId) {
		OrderInfoQuery listQuery = new OrderInfoQuery();
		listQuery.setPayOrderId(payOrderId);
		List<OrderInfo> orderList = orderInfoMapper.selectList(listQuery);
		if (orderList.isEmpty()) {
			return;
		}
		for (OrderInfo order : orderList) {
			if (isPaidOrBeyond(order.getOrderStatus())) {
				log.info("支付超时关单跳过：存在已支付子单 payOrderId={}", payOrderId);
				return;
			}
		}
		int rows = orderStateMachine.transitionPayOrder(payOrderId, OrderStatusEnum.WAIT_PAYMENT,
				OrderStateEvent.PAYMENT_TIMEOUT);
		if (rows == 0) {
			log.info("支付超时关单无待付款子单 payOrderId={}", payOrderId);
			return;
		}
		if (rows != orderList.size()) {
			throw new BusinessException("支付超时关单失败，子订单状态已变化");
		}
		markPayOrderClosedIfNeeded(payOrderId);
		payFeignSupport.markClosed(payOrderId);
		OrderInfo channelRef = orderList.stream()
				.filter(o -> !StringTools.isEmpty(o.getChannelOrderId()))
				.findFirst()
				.orElse(orderList.get(0));
		cancelOrder4Channel(channelRef);
		releaseCouponIfNeeded(payOrderId);
		restoreStockForOrders(payOrderId, orderList);
		recordCancellationOutcomes(orderList, "PAYMENT_TIMEOUT", "CLOSED");
	}

	private void restoreStockForOrders(String restoreReferenceId, List<OrderInfo> orderList) {
		if (StringTools.isEmpty(restoreReferenceId) || orderList == null || orderList.isEmpty()) {
			return;
		}
		List<ProductItem> newList = new ArrayList<>();
		for (OrderInfo orderInfo1 : orderList) {
			OrderItemQuery orderItemQuery = new OrderItemQuery();
			orderItemQuery.setOrderId(orderInfo1.getOrderId());
			List<OrderItem> orderItemList = orderItemMapper.selectList(orderItemQuery);
			for (OrderItem orderItem : orderItemList) {
				ProductItem productItem = new ProductItem();
				productItem.setProductId(orderItem.getProductId());
				productItem.setPropertyValueIdHash(orderItem.getPropertyValueIdHash());
				productItem.setBuyCount(orderItem.getBuyCount());
				newList.add(productItem);
			}
		}
		if (newList.isEmpty()) {
			throw new BusinessException("商品列表为空");
		}
		try {
			stockFeignSupport.restoreOrderStock(restoreReferenceId, newList);
		} catch (Exception e) {
			log.error("关单库存回补失败, referenceId={}", restoreReferenceId, e);
			remoteCompensateRecorder.recordOrderStockRestore(restoreReferenceId, newList, e);
		}
	}

		// 支付成功信息
	@Override
	@Transactional(rollbackFor = Exception.class)
	public void paySuccess(PayOrderNotifyDTO payOrderNotifyDTO) {
		if (payOrderNotifyDTO == null || StringTools.isEmpty(payOrderNotifyDTO.getPayOrderId())) {
			throw new BusinessException("支付订单号无效");
		}
		String payOrderId = payOrderNotifyDTO.getPayOrderId();
		payOrderRedisComponent.runWithPayOrderLifecycleLock(payOrderId,
				() -> paySuccessInLock(payOrderNotifyDTO));
	}

	private void paySuccessInLock(PayOrderNotifyDTO payOrderNotifyDTO) {
		String payOrderId = payOrderNotifyDTO.getPayOrderId();
		payFeignSupport.assertSettled(payOrderId);
		List<OrderInfo> orderInfoList = loadOrdersByPayOrderId(payOrderId);
		if (orderInfoList.isEmpty()) {
			throw new BusinessException("订单不存在");
		}
		if (orderInfoList.stream().anyMatch(this::isCouponRushOrder)) {
			paySuccessForCouponRush(orderInfoList, payOrderNotifyDTO);
			return;
		}
		if (orderInfoList.stream().allMatch(o -> isPaidOrBeyond(o.getOrderStatus()))) {
			log.info("paySuccess 幂等跳过 payOrderId={}", payOrderId);
			return;
		}
		if (orderInfoList.stream().anyMatch(o -> isClosedOrCancelled(o.getOrderStatus()))) {
			handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
			return;
		}
		// 获取同一payOrderId下的订单中不为null的收货信息
		OrderLogisticsInfo logisticsInfo = new OrderLogisticsInfo();
		// 根据orderId查询不为null的收货信息
		for (OrderInfo orderInfo : orderInfoList) {
			if (orderInfo == null ) {
				throw new BusinessException("订单不存在");
			}
			String orderId = orderInfo.getOrderId();
			logisticsInfo = orderLogisticsInfoMapper.selectByOrderId(orderId);
			if (logisticsInfo == null) {
				continue;
			}
            break;
        }
		// 从redis中获得默认发货信息
		LogisticsSendDTO sendLogisticsSendDTO = redisComponent.getLogisticsInfo();
		// 把所有同一payOrderId下的订单都设置同样的收货信息
		for (OrderInfo orderInfo : orderInfoList) {
			// 根据orderId查询物流Info
			OrderLogisticsInfo orderLogisticsInfo = orderLogisticsInfoMapper.selectByOrderId(orderInfo.getOrderId());
			if (orderLogisticsInfo == null){
				// 如果没有则插入
				orderLogisticsInfo = new OrderLogisticsInfo();
				orderLogisticsInfo.setOrderId(orderInfo.getOrderId());
				orderLogisticsInfo.setUserId(orderInfo.getUserId());
				orderLogisticsInfo.setReceiverName(logisticsInfo.getReceiverName());
				orderLogisticsInfo.setReceiverPhone(logisticsInfo.getReceiverPhone());
				orderLogisticsInfo.setReceiverAddress(logisticsInfo.getReceiverAddress());
				orderLogisticsInfo.setLogisticsStatus(LogisticsStatusEnum.PENDING_SHIPMENT.getStatus());
				if (sendLogisticsSendDTO != null) {
					orderLogisticsInfo.setSenderName(sendLogisticsSendDTO.getSenderName());
					orderLogisticsInfo.setSenderPhone(sendLogisticsSendDTO.getSenderPhone());
					orderLogisticsInfo.setSenderAddress(sendLogisticsSendDTO.getSenderAddress());
				}
				orderLogisticsInfoMapper.insert(orderLogisticsInfo);
			}else {
				// 更新
				OrderLogisticsInfoQuery orderLogisticsInfoQuery = new OrderLogisticsInfoQuery();
				orderLogisticsInfoQuery.setOrderId(orderInfo.getOrderId());
				orderLogisticsInfoQuery.setUserId(orderInfo.getUserId());
                orderLogisticsInfo.setReceiverName(logisticsInfo.getReceiverName());
				orderLogisticsInfo.setReceiverPhone(logisticsInfo.getReceiverPhone());
				orderLogisticsInfo.setReceiverAddress(logisticsInfo.getReceiverAddress());
				if (sendLogisticsSendDTO != null) {
					orderLogisticsInfo.setSenderName(sendLogisticsSendDTO.getSenderName());
					orderLogisticsInfo.setSenderPhone(sendLogisticsSendDTO.getSenderPhone());
					orderLogisticsInfo.setSenderAddress(sendLogisticsSendDTO.getSenderAddress());
				}
				orderLogisticsInfoMapper.updateByParam(orderLogisticsInfo, orderLogisticsInfoQuery);
			}
		}
		int updatedCount = 0;
		for (OrderInfo orderInfo : orderInfoList) {
			orderInfo.setChannelOrderId(payOrderNotifyDTO.getChannelOrderId());
			orderInfo.setOrderStatus(OrderStatusEnum.PAID.getStatus());
			int rows = orderStateMachine.transition(orderInfo.getOrderId(), OrderStatusEnum.WAIT_PAYMENT,
					OrderStateEvent.PAY_SUCCESS, orderInfo);
			if (rows > 0) {
				updatedCount++;
				PayOrderMessageDTO dto = new PayOrderMessageDTO();
				dto.setOrderId(orderInfo.getOrderId());
				dto.setLogisticsStep(0);
				transactionalMqSender.sendAfterCommit(
						RabbitMQConfig.PAY_EXCHANGE,
						RabbitMQConfig.PAY_LOGISTICS_DELAY_KEY,
						dto,
						MqIdempotencyKeys.payLogistics(orderInfo.getOrderId(), 0),
						MessageReliabilityLevelEnum.STANDARD);
			}
		}
		if (updatedCount == 0) {
			handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
			return;
		}
		if (updatedCount < orderInfoList.size()) {
			throw new BusinessException("支付成功处理失败，部分订单状态异常");
		}

		useCouponIfNeeded(orderInfoList);
		payFeignSupport.markSuccess(payOrderId, payOrderNotifyDTO.getChannelOrderId());
		recordPaymentOutcomes(orderInfoList, payOrderId);
	}

	private PayChannelEnum resolveWaitPayChannel(OrderInfo orderInfo) {
		PayChannelEnum payChannelEnum = PayChannelEnum.resolve(orderInfo.getPayChannel());
		if (payChannelEnum != null) {
			return payChannelEnum;
		}
		payChannelEnum = PayChannelEnum.ALIPAY_PC;
		OrderInfo patch = new OrderInfo();
		patch.setPayChannel(payChannelEnum.getPayScene());
		OrderInfoQuery patchQuery = new OrderInfoQuery();
		patchQuery.setOrderId(orderInfo.getOrderId());
		patchQuery.setOrderStatus(OrderStatusEnum.WAIT_PAYMENT.getStatus());
		orderInfoMapper.updateByParam(patch, patchQuery);
		orderInfo.setPayChannel(payChannelEnum.getPayScene());
		return payChannelEnum;
	}

	private boolean isCouponRushOrder(OrderInfo orderInfo) {
		if (orderInfo == null || orderInfo.getPayScene() == null) {
			return false;
		}
		return String.valueOf(OrderFromTypeEnum.COUPON.getType()).equals(orderInfo.getPayScene());
	}

	private void cancelCouponRushOrder(String orderId, String userId) {
		OrderStateEvent cancelEvent = userId != null ? OrderStateEvent.USER_CANCEL : OrderStateEvent.SYSTEM_CANCEL;
		int rows = orderStateMachine.transition(orderId, OrderStatusEnum.WAIT_PAYMENT, cancelEvent);
		if (rows == 0) {
			return;
		}
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			return;
		}
		markPayOrderClosedIfNeeded(orderInfo.getPayOrderId());
		OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
		relQuery.setOrderId(orderId);
		List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
		for (OrderCouponRel rel : rels) {
			if (!StringTools.isEmpty(rel.getCouponId())) {
				couponFeignSupport.releaseRushCouponReserve(rel.getCouponId(), orderInfo.getUserId());
			}
		}
	}

	@Override
	public void syncPaidCouponRushUserCoupons(String userId) {
		couponRushOrderService.syncPaidCouponRushUserCoupons(userId);
	}

	private void paySuccessForCouponRush(List<OrderInfo> orderInfoList, PayOrderNotifyDTO payOrderNotifyDTO) {
		String payOrderId = payOrderNotifyDTO.getPayOrderId();
		if (orderInfoList.stream().allMatch(o -> OrderStatusEnum.COMPLETED.getStatus().equals(o.getOrderStatus()))) {
			log.info("couponRush paySuccess 幂等跳过 payOrderId={}", payOrderId);
			return;
		}
		if (orderInfoList.stream().anyMatch(o -> isClosedOrCancelled(o.getOrderStatus()))) {
			handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
			return;
		}
		int updatedCount = 0;
		for (OrderInfo orderInfo : orderInfoList) {
			orderInfo.setChannelOrderId(payOrderNotifyDTO.getChannelOrderId());
			orderInfo.setOrderStatus(OrderStatusEnum.COMPLETED.getStatus());
			int rows = orderStateMachine.transition(orderInfo.getOrderId(), OrderStatusEnum.WAIT_PAYMENT,
					OrderStateEvent.COUPON_RUSH_PAY_SUCCESS, orderInfo);
			if (rows == 0) {
				continue;
			}
			updatedCount++;
			OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
			relQuery.setOrderId(orderInfo.getOrderId());
			List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
			for (OrderCouponRel rel : rels) {
				couponRushOrderService.activateUserCoupon(orderInfo.getUserId(), rel.getUserCouponId());
			}
		}
		if (updatedCount == 0) {
			handlePaySuccessConflict(payOrderId, payOrderNotifyDTO);
			return;
		}
		if (updatedCount < orderInfoList.size()) {
			throw new BusinessException("支付成功处理失败，部分订单状态异常");
		}
		payFeignSupport.markSuccess(payOrderId, payOrderNotifyDTO.getChannelOrderId());
		log.info("优惠券秒杀支付成功 payOrderId={}, 券数量={}", payOrderId, orderInfoList.size());
	}

	private List<OrderInfo> loadOrdersByPayOrderId(String payOrderId) {
		OrderInfoQuery query = new OrderInfoQuery();
		query.setPayOrderId(payOrderId);
		return orderInfoMapper.selectList(query);
	}

	private boolean isClosedOrCancelled(Integer status) {
		return OrderStatusEnum.CLOSED.getStatus().equals(status)
				|| OrderStatusEnum.CANCELLED.getStatus().equals(status);
	}

	private void markPayOrderClosedIfNeeded(String payOrderId) {
		if (!StringTools.isEmpty(payOrderId)) {
			payOrderRedisComponent.tryMarkPayOrderCloseOnce(payOrderId);
		}
	}

	private void handlePaySuccessConflict(String payOrderId, PayOrderNotifyDTO payOrderNotifyDTO) {
		List<OrderInfo> latest = loadOrdersByPayOrderId(payOrderId);
		if (latest.isEmpty()) {
			throw new BusinessException("订单不存在");
		}
		if (latest.stream().allMatch(o -> isPaidOrBeyond(o.getOrderStatus())
				|| OrderStatusEnum.COMPLETED.getStatus().equals(o.getOrderStatus()))) {
			log.info("paySuccess 幂等跳过 payOrderId={}", payOrderId);
			return;
		}
		if (latest.stream().anyMatch(o -> isClosedOrCancelled(o.getOrderStatus()))) {
			refundLatePaymentAfterClose(payOrderId, payOrderNotifyDTO, latest);
			return;
		}
		throw new BusinessException("支付成功处理失败，订单状态异常");
	}

	private void refundLatePaymentAfterClose(String payOrderId, PayOrderNotifyDTO payOrderNotifyDTO,
			List<OrderInfo> orders) {
		if (!payOrderRedisComponent.tryMarkLatePaymentRefundOnce(payOrderId)) {
			log.info("关单后迟到支付退款幂等跳过 payOrderId={}", payOrderId);
			return;
		}
		BigDecimal total = orders.stream()
				.map(OrderInfo::getAmount)
				.filter(Objects::nonNull)
				.reduce(BigDecimal.ZERO, BigDecimal::add);
		if (total.compareTo(BigDecimal.ZERO) <= 0) {
			log.warn("关单后迟到支付退款金额为0 payOrderId={}", payOrderId);
			return;
		}
		OrderInfo refOrder = orders.get(0);
		PayChannelEnum payChannelEnum = resolveWaitPayChannel(refOrder);
		String refundRequestNo = "LATE" + StringTools.getRandomNumber(Constants.LENGTH_30);
		try {
			payFeignSupport.refund(payOrderId, refundRequestNo, total, payChannelEnum.getPayScene());
			payFeignSupport.markRefunded(payOrderId);
			log.warn("关单后迟到的支付已原路退款 payOrderId={}, channelOrderId={}, amount={}",
					payOrderId, payOrderNotifyDTO.getChannelOrderId(), total);
		} catch (Exception e) {
			payOrderRedisComponent.clearLatePaymentRefundMark(payOrderId);
			throw new BusinessException("关单后支付退款失败：" + e.getMessage(), e);
		}
	}

	private void releaseCouponIfNeeded(String payOrderId) {
		if (StringTools.isEmpty(payOrderId)) {
			return;
		}
		OrderInfoQuery q = new OrderInfoQuery();
		q.setPayOrderId(payOrderId);
		List<OrderInfo> orders = orderInfoMapper.selectList(q);
		for (OrderInfo o : orders) {
			if (isCouponRushOrder(o)) {
				continue;
			}
			OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
			relQuery.setOrderId(o.getOrderId());
			List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
			for (OrderCouponRel rel : rels) {
				if (StringTools.isEmpty(rel.getUserCouponId())) {
					continue;
				}
				UserCouponVO uc = couponFeignSupport.getUserCoupon(rel.getUserCouponId());
				if (uc != null && UserCouponStatusEnum.CANT.getStatus().equals(uc.getStatus())) {
					try {
						couponFeignSupport.changeUserCouponStatus(uc.getUserCouponId(), uc.getUserId(),
								UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(), null);
					} catch (Exception compensateEx) {
						log.error("关单优惠券解锁失败, payOrderId={}, userCouponId={}",
								payOrderId, uc.getUserCouponId(), compensateEx);
						remoteCompensateRecorder.recordCouponUnlock(
								payOrderId, uc.getUserCouponId(), uc.getUserId(),
								UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.NOUSE.getStatus(),
								compensateEx);
					}
				}
			}
		}
	}

	private void useCouponIfNeeded(List<OrderInfo> orderInfoList) {
		if (orderInfoList == null || orderInfoList.isEmpty()) {
			return;
		}
		Date now = new Date();
		for (OrderInfo o : orderInfoList) {
			OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
			relQuery.setOrderId(o.getOrderId());
			List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
			for (OrderCouponRel rel : rels) {
				if (StringTools.isEmpty(rel.getUserCouponId())) {
					continue;
				}
				try {
					couponFeignSupport.changeUserCouponStatus(rel.getUserCouponId(), o.getUserId(),
							UserCouponStatusEnum.CANT.getStatus(), UserCouponStatusEnum.USED.getStatus(), now);
				} catch (BusinessException ex) {
					// 幂等：券已是 USED 时忽略；其它业务失败需抛出以便支付回调重试
					UserCouponVO uc = null;
					try {
						uc = couponFeignSupport.getUserCoupon(rel.getUserCouponId());
					} catch (Exception ignore) {
					}
					if (uc != null && UserCouponStatusEnum.USED.getStatus().equals(uc.getStatus())) {
						continue;
					}
					log.error("支付成功后核销优惠券失败, orderId={}, userCouponId={}, msg={}",
							o.getOrderId(), rel.getUserCouponId(), ex.getMessage());
					throw ex;
				}
			}
		}
	}

	@Override
	public void refund(OrderItem orderItem, String userId) {
		refundSagaService.requestRefund(orderItem, userId);
	}

	@Override
	public List<OrderCountVO> getOrderCountInfo(String userId) {
		OrderInfoQuery query = new OrderInfoQuery();
		query.setUserId(userId);
		List<OrderInfo> orderInfoList = orderInfoMapper.selectList(query);
		OrderCountVO orderCountVO1 = new OrderCountVO();
		OrderCountVO orderCountVO2 = new OrderCountVO();
		OrderCountVO orderCountVO3 = new OrderCountVO();
		OrderCountVO orderCountVO4 = new OrderCountVO();
		OrderCountVO orderCountVO5 = new OrderCountVO();
		List<OrderCountVO> orderCountVOList = new ArrayList<>();
		Integer waitPayCount = 0;
		Integer waitShipCount = 0;
		Integer waitReceiveCount = 0;
		Integer waitCommentCount = 0;
		Set<String> completedPayOrderIds = new HashSet<>();
		for (OrderInfo orderInfo : orderInfoList) {
			boolean isCouponOrder = "2".equals(orderInfo.getPayScene());
			// 已删除的不统计
			if (OrderStatusEnum.DELETE.getStatus().equals(orderInfo.getOrderStatus())){
				continue;
			}
			if (OrderStatusEnum.WAIT_PAYMENT.getStatus().equals(orderInfo.getOrderStatus())){
				waitPayCount++;
			} else if (OrderStatusEnum.PAID.getStatus().equals(orderInfo.getOrderStatus())) {
				waitShipCount++;
			}else if(OrderStatusEnum.SHIPPED.getStatus().equals(orderInfo.getOrderStatus())){
				waitReceiveCount++;
			}else if (OrderStatusEnum.COMPLETED.getStatus().equals(orderInfo.getOrderStatus())
				&& !isCouponOrder
				&& OrderCommentStatusEnum.NOT_EVALUATED.getStatus().equals(orderInfo.getCommentStatus())){
			waitCommentCount++;
			}
			if (OrderStatusEnum.COMPLETED.getStatus().equals(orderInfo.getOrderStatus())){
				completedPayOrderIds.add(orderInfo.getOrderId());
			}
		}
		Integer completedCount = completedPayOrderIds.size();
		orderCountVO1.setCode("pendingPayment");
		orderCountVO1.setCount(waitPayCount);
		orderCountVOList.add(orderCountVO1);
		orderCountVO2.setCode("pendingShipment");
		orderCountVO2.setCount(waitShipCount);
		orderCountVOList.add(orderCountVO2);
		orderCountVO3.setCode("pendingReceipt");
		orderCountVO3.setCount(waitReceiveCount);
		orderCountVOList.add(orderCountVO3);
		orderCountVO4.setCode("pendingComment");
		orderCountVO4.setCount(waitCommentCount);
		orderCountVOList.add(orderCountVO4);
		orderCountVO5.setCode("completed");
		orderCountVO5.setCount(completedCount);
		orderCountVOList.add(orderCountVO5);
		return orderCountVOList;
	}

	@Override
	public PaginationResultVO<OrderInfo> findByProductNameFuzzy(PaginationResultVO<OrderInfo> resultVO, String productNameFuzzy) {
		List<OrderInfo> orderInfoList = resultVO.getList();
		List<OrderInfo> newList = new ArrayList<>();
		int flag;
		for (OrderInfo orderInfo : orderInfoList) {
			flag = 0;
			for (OrderItem orderItem : orderInfo.getOrderItemList()){
				if (!orderItem.getProductName().contains(productNameFuzzy)) {
					continue;
				}
				if (flag == 1) {
					continue;
				}
				flag = 1;
				newList.add(orderInfo);
			}
		}
		resultVO.setList(newList);
		return resultVO;
	}

	@Override
	public void addAllOrderToDelayQueue(List<OrderInfo> orderInfoList) {
		// 将orderId逐个加入到延迟队列（事务提交后发送）
		for (OrderInfo orderInfo : orderInfoList) {
			PayOrderMessageDTO dto = new PayOrderMessageDTO();
			dto.setOrderId(orderInfo.getOrderId());
			transactionalMqSender.sendAfterCommit(
					RabbitMQConfig.PAY_EXCHANGE,
					RabbitMQConfig.PAY_TIMEOUT_DELAY_KEY,
					dto,
					MqIdempotencyKeys.payTimeout(orderInfo.getOrderId()),
					MessageReliabilityLevelEnum.STANDARD);
		}
	}

	@Override
	public void enrichCouponInfo(OrderInfo orderInfo) {
		if (orderInfo == null) {
			return;
		}
		if (isCouponRushOrder(orderInfo)) {
			BigDecimal amt = orderInfo.getAmount() == null ? BigDecimal.ZERO : orderInfo.getAmount();
			orderInfo.setOriginalAmount(amt);
			orderInfo.setCouponDiscountAmount(BigDecimal.ZERO);
			return;
		}
		BigDecimal original = sumItemAmount(orderInfo.getOrderItemList(), true);
		BigDecimal payAmount = orderInfo.getAmount() == null ? BigDecimal.ZERO : orderInfo.getAmount();
		orderInfo.setOriginalAmount(original);
		BigDecimal discount = original.subtract(payAmount);
		if (discount.compareTo(BigDecimal.ZERO) < 0) {
			discount = BigDecimal.ZERO;
		}
		discount = discount.setScale(2, RoundingMode.HALF_UP);
		orderInfo.setCouponDiscountAmount(discount);
		if (discount.compareTo(BigDecimal.ZERO) <= 0) {
			return;
		}
		OrderCouponRel rel = findCouponRelForOrder(orderInfo);
		if (rel == null || StringTools.isEmpty(rel.getCouponId())) {
			return;
		}
		CouponBriefVO coupon = couponFeignSupport.getCouponBrief(rel.getCouponId());
		if (coupon != null) {
			orderInfo.setCouponName(coupon.getCouponName());
			orderInfo.setCouponType(coupon.getCouponType());
		}
	}

	@Override
	public void enrichCouponInfo(List<OrderInfo> orderInfoList) {
		if (orderInfoList == null || orderInfoList.isEmpty()) {
			return;
		}
		for (OrderInfo orderInfo : orderInfoList) {
			enrichCouponInfo(orderInfo);
		}
	}

	private void enrichUserBrief(List<OrderInfo> list) {
		List<String> userIds = list.stream()
				.map(OrderInfo::getUserId)
				.filter(id -> !StringTools.isEmpty(id))
				.distinct()
				.collect(Collectors.toList());
		Map<String, UserBriefVO> map = userFeignSupport.mapBriefByUserIds(userIds);
		for (OrderInfo order : list) {
			UserBriefVO brief = map.get(order.getUserId());
			if (brief != null) {
				order.setNickName(brief.getNickName());
				order.setAvatar(brief.getAvatar());
			}
		}
	}

	private BigDecimal sumItemAmount(List<OrderItem> items, boolean normalOnly) {
		BigDecimal total = BigDecimal.ZERO;
		if (items == null) {
			return total;
		}
		for (OrderItem item : items) {
			if (normalOnly && !OrderItemStatusEnum.NORMAL.getStatus().equals(item.getOrderItemStatus())) {
				continue;
			}
			BigDecimal itemAmount = item.getItemAmount() == null ? BigDecimal.ZERO : item.getItemAmount();
			total = total.add(itemAmount);
		}
		return total.setScale(2, RoundingMode.HALF_UP);
	}

	private OrderCouponRel findCouponRelForOrder(OrderInfo orderInfo) {
		OrderCouponRelQuery relQuery = new OrderCouponRelQuery();
		relQuery.setOrderId(orderInfo.getOrderId());
		List<OrderCouponRel> rels = orderCouponRelMapper.selectList(relQuery);
		if (rels != null && !rels.isEmpty()) {
			return rels.get(0);
		}
		if (StringTools.isEmpty(orderInfo.getPayOrderId())) {
			return null;
		}
		OrderInfoQuery siblingQuery = new OrderInfoQuery();
		siblingQuery.setPayOrderId(orderInfo.getPayOrderId());
		List<OrderInfo> siblings = orderInfoMapper.selectList(siblingQuery);
		if (siblings == null) {
			return null;
		}
		for (OrderInfo sibling : siblings) {
			if (sibling == null || orderInfo.getOrderId().equals(sibling.getOrderId())) {
				continue;
			}
			relQuery.setOrderId(sibling.getOrderId());
			rels = orderCouponRelMapper.selectList(relQuery);
			if (rels != null && !rels.isEmpty()) {
				return rels.get(0);
			}
		}
		return null;
	}

	@Override
	public void onOrderConfirmed(String userId, String orderId) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo != null && OrderCommentStatusEnum.EVALUATED.getStatus().equals(orderInfo.getCommentStatus())) {
			orderNotificationPublisher.send(userId, "追评提醒",
					"订单已完成，欢迎追加评价分享购物体验", "comment_re", orderId);
		} else {
			orderNotificationPublisher.send(userId, "确认收货成功",
					"订单已完成，欢迎评价商品获取成长值", "order", orderId);
		}
	}

	@Override
	@Transactional(rollbackFor = Exception.class)
	public boolean confirmOrderReceipt(String userId, String orderId) {
		if (StringTools.isEmpty(orderId)) {
			throw new BusinessException("订单不存在");
		}
		OrderInfo existing = orderInfoMapper.selectByOrderId(orderId);
		if (existing == null) {
			throw new BusinessException("订单不存在");
		}
		if (userId != null && !userId.equals(existing.getUserId())) {
			throw new BusinessException("订单不存在");
		}
		if (OrderStatusEnum.COMPLETED.getStatus().equals(existing.getOrderStatus())) {
			return false;
		}
		int rows = orderStateMachine.transition(orderId,
				Set.of(OrderStatusEnum.SHIPPED, OrderStatusEnum.PARTIALLY_REFUNDED),
				OrderStateEvent.CONFIRM_RECEIPT);
		if (rows == 0) {
			return false;
		}
		enqueueOrderGrowth(existing);
		increaseProductSalesForOrder(orderId);
		return true;
	}

	private void enqueueOrderGrowth(OrderInfo orderInfo) {
		if (orderInfo == null
				|| StringTools.isEmpty(orderInfo.getOrderId())
				|| StringTools.isEmpty(orderInfo.getUserId())
				|| orderInfo.getAmount() == null
				|| orderInfo.getAmount().compareTo(BigDecimal.ZERO) <= 0) {
			return;
		}
		OrderGrowthEventDTO event = new OrderGrowthEventDTO(
				orderInfo.getOrderId(), orderInfo.getUserId(), orderInfo.getAmount());
		transactionalMqSender.sendAfterCommit(
				RabbitMQConfig.USER_MEMBER_EXCHANGE,
				RabbitMQConfig.USER_MEMBER_KEY,
				event,
				MqIdempotencyKeys.orderGrowth(orderInfo.getOrderId()),
				MessageReliabilityLevelEnum.STANDARD);
	}

	@Override
	public boolean cancelUnpaidOrderForPayTimeout(String orderId) {
		OrderInfo orderInfo = orderInfoMapper.selectByOrderId(orderId);
		if (orderInfo == null) {
			return true;
		}
		if (!Objects.equals(orderInfo.getOrderStatus(), OrderStatusEnum.WAIT_PAYMENT.getStatus())) {
			return true;
		}
		String payId = orderInfo.getPayOrderId();
		if (payId != null) {
			OrderInfoQuery query = new OrderInfoQuery();
			query.setPayOrderId(payId);
			List<OrderInfo> orderInfoList = orderInfoMapper.selectList(query);
			for (OrderInfo order : orderInfoList) {
				if (isPaidOrBeyond(order.getOrderStatus())) {
					return true;
				}
			}
		}
		try {
			cancelOrder(null, orderId, OrderStatusEnum.CLOSED);
		} catch (PayOrderLifecycleBusyException e) {
			log.warn("支付超时关单生命周期锁忙，稍后 requeue orderId={}", orderId);
			return false;
		}
		return true;
	}

	private void increaseProductSalesForOrder(String orderId) {
		OrderItemQuery itemQuery = new OrderItemQuery();
		itemQuery.setOrderId(orderId);
		List<OrderItem> items = orderItemMapper.selectList(itemQuery);
		if (items == null || items.isEmpty()) {
			log.warn("确认收货无商品明细 orderId={}", orderId);
			return;
		}
		Map<String, Integer> qtyByProduct = new HashMap<>();
		for (OrderItem item : items) {
			if (StringTools.isEmpty(item.getProductId()) || item.getBuyCount() == null) {
				continue;
			}
			qtyByProduct.merge(item.getProductId(), item.getBuyCount(), Integer::sum);
		}
		for (Map.Entry<String, Integer> entry : qtyByProduct.entrySet()) {
			try {
				productFeignSupport.increaseSales(entry.getKey(), entry.getValue());
			} catch (BusinessException e) {
				log.warn("确认收货加销量跳过 productId={}, msg={}", entry.getKey(), e.getMessage());
			}
		}
	}

	private void recordPaymentOutcomes(List<OrderInfo> orders, String payOrderId) {
		if (orders == null || orders.isEmpty()) {
			return;
		}
		Date occurredAt = new Date();
		List<String> currentOrderIds = orders.stream()
				.map(OrderInfo::getOrderId)
				.filter(Objects::nonNull)
				.toList();
		for (OrderInfo order : orders) {
			List<OrderItem> items = new ArrayList<>(loadOrderItems(order.getOrderId()));
			items.sort(Comparator.comparing(OrderItem::getOrderItemId));
			if (items.isEmpty()) {
				continue;
			}
			BigDecimal grossTotal = items.stream().map(item -> normalizeMoney(item.getItemAmount()))
                    .reduce(BigDecimal.ZERO, BigDecimal::add);
            BigDecimal orderPaid = normalizeMoney(order.getAmount());
            if (orderPaid.compareTo(grossTotal) > 0) {
                throw new BusinessException("订单实付超过商品原价合计");
            }
            BigDecimal cumulativeGross = BigDecimal.ZERO;
            BigDecimal allocated = BigDecimal.ZERO;
			for (int index = 0; index < items.size(); index++) {
				OrderItem item = items.get(index);
				boolean repeatPurchase = hasPriorSuccessfulPurchase(
						order.getUserId(), item.getProductId(), currentOrderIds);
                cumulativeGross = cumulativeGross.add(item.getItemAmount());
                // Fixed payment basis; cumulative rounding prevents a tiny final line absorbing excess cents.
                BigDecimal cumulativePaid = index == items.size() - 1 || grossTotal.signum() == 0
                        ? orderPaid
                        : orderPaid.multiply(cumulativeGross).divide(grossTotal, 2, RoundingMode.HALF_UP);
                BigDecimal paidAmount = cumulativePaid.subtract(allocated).setScale(2);
                allocated = cumulativePaid;
                if (item.getPaidAmount() == null) {
                    if (orderItemMapper.recordPaidAmount(item.getOrderItemId(), paidAmount) != 1) {
                        throw new BusinessException("订单明细实付保存失败");
                    }
                    item.setPaidAmount(paidAmount);
                } else if (item.getPaidAmount().compareTo(paidAmount) != 0) {
                    throw new BusinessException("订单明细实付与已确认金额不一致");
                }
				Map<String, Object> payload = new LinkedHashMap<>();
				if (item.getBuyCount() != null) {
					payload.put("quantity", item.getBuyCount());
				}
				payload.put("paidAmount", paidAmount);
				payload.put("payOrderId", payOrderId);
				payload.put("orderItemId", item.getOrderItemId());
				payload.put("currency", "CNY");
				payload.put("payStatus", "PAID");
				payload.put("attribution", orderAttributionService.eventAttribution(order.getOrderId()));
				commerceOutcomeClient.recordV2AfterCommit(CommerceOutcomeClient.fromVerifiedCarrier(
						CommerceOutcomeClient.stableEventId(
								"payment", payOrderId, order.getOrderId(), item.getOrderItemId()),
						"PAYMENT",
						CommerceOutcomeClient.stableIdempotencyKey(
								"payment", payOrderId, order.getOrderId(), item.getOrderItemId()),
						"PAYMENT",
						order.getUserId(),
						item,
						item.getPropertyValueIdHash(),
						order.getOrderId(),
						payload,
						occurredAt));
				if (repeatPurchase) {
					Map<String, Object> repeatPayload = new LinkedHashMap<>();
					if (item.getBuyCount() != null) {
						repeatPayload.put("quantity", item.getBuyCount());
					}
					repeatPayload.put("paidAmount", paidAmount);
					repeatPayload.put("payOrderId", payOrderId);
					repeatPayload.put("orderItemId", item.getOrderItemId());
					repeatPayload.put("currency", "CNY");
					commerceOutcomeClient.recordAfterCommit(
							CommerceOutcomeClient.fromVerifiedCarrier(
									CommerceOutcomeClient.stableEventId(
											"repeat-purchase", payOrderId,
											order.getOrderId(), item.getOrderItemId()),
									"ORDER",
									CommerceOutcomeClient.stableIdempotencyKey(
											"repeat-purchase", payOrderId,
											order.getOrderId(), item.getOrderItemId()),
									"REPEAT_PURCHASE",
									order.getUserId(),
									item,
									item.getPropertyValueIdHash(),
									order.getOrderId(),
									repeatPayload,
									occurredAt));
				}
			}
		}
	}

	private boolean hasPriorSuccessfulPurchase(
			String userId, String productId, List<String> currentOrderIds) {
		if (StringTools.isEmpty(userId) || StringTools.isEmpty(productId)) {
			return false;
		}
		Integer count = orderItemMapper.countPriorSuccessfulPurchases(
				userId,
				productId,
				currentOrderIds,
				List.of(
						OrderStatusEnum.PAID.getStatus(),
						OrderStatusEnum.SHIPPED.getStatus(),
						OrderStatusEnum.COMPLETED.getStatus(),
						OrderStatusEnum.PARTIALLY_REFUNDED.getStatus()));
		return count != null && count > 0;
	}

	private void recordCancellationOutcomes(
			List<OrderInfo> orders, String reasonCode, String orderStatus) {
		if (orders == null || orders.isEmpty()) {
			return;
		}
		Date occurredAt = new Date();
		for (OrderInfo order : orders) {
			for (OrderItem item : loadOrderItems(order.getOrderId())) {
				Map<String, Object> payload = new LinkedHashMap<>();
				payload.put("reasonCode", reasonCode);
				payload.put("orderStatus", orderStatus);
				commerceOutcomeClient.recordAfterCommit(CommerceOutcomeClient.fromVerifiedCarrier(
						CommerceOutcomeClient.stableEventId(
								"cancel", order.getOrderId(), item.getOrderItemId()),
						"ORDER",
						CommerceOutcomeClient.stableIdempotencyKey(
								"cancel", order.getOrderId(), item.getOrderItemId()),
						"CANCEL",
						order.getUserId(),
						item,
						item.getPropertyValueIdHash(),
						order.getOrderId(),
						payload,
						occurredAt));
			}
		}
	}

	private List<OrderItem> loadOrderItems(String orderId) {
		if (StringTools.isEmpty(orderId)) {
			return Collections.emptyList();
		}
		OrderItemQuery query = new OrderItemQuery();
		query.setOrderId(orderId);
		List<OrderItem> items = orderItemMapper.selectList(query);
		return items == null ? Collections.emptyList() : items;
	}

	private BigDecimal normalizeMoney(BigDecimal amount) {
        if (amount == null || amount.signum() < 0) {
            throw new BusinessException("订单金额必须为非负金额");
        }
        try {
            return amount.setScale(2, RoundingMode.UNNECESSARY);
        } catch (ArithmeticException exception) {
            throw new BusinessException("订单金额必须精确到分");
        }
    }

	// 关闭订单（支付系统官方）
	private void cancelOrder4Channel(OrderInfo orderInfo) {
		PayChannelEnum payChannelEnum = PayChannelEnum.resolve(orderInfo.getPayChannel());
		if (payChannelEnum == null) {
			return;
		}
		try {
			payFeignSupport.closeOrder(orderInfo.getPayOrderId(), payChannelEnum.getPayScene());
		} catch (RuntimeException ex) {
			if ("支付宝支付未配置".equals(ex.getMessage())) {
				log.info("支付渠道未启用，跳过不存在的外部交易关单, payOrderId={}", orderInfo.getPayOrderId());
				return;
			}
			throw ex;
		}
	}

	private List<ProductItem> copyItemsWithSignedBuyCount(List<ProductItem> source, boolean negate) {
		List<ProductItem> copy = new ArrayList<>(source.size());
		for (ProductItem item : source) {
			ProductItem pi = new ProductItem();
			pi.setProductId(item.getProductId());
			pi.setPropertyValueIdHash(item.getPropertyValueIdHash());
			int qty = item.getBuyCount() == null ? 0 : item.getBuyCount();
			pi.setBuyCount(negate ? -Math.abs(qty) : Math.abs(qty));
			copy.add(pi);
		}
		return copy;
	}
}
