-- V2：试玩账号播种所需 4 表。Phase2 Flyway V 化把快照收敛进 V1 时遗漏了它们
-- （本地老库天然存在故未暴露；全新库上 TrialAccountService 启动即失败）。
-- 其余快照缺口（签到/评论/归因/分析线等）经存活引用核验均为已退役功能，不补。
-- DDL 取自演进库现状，全部 IF NOT EXISTS，对已有库幂等。

CREATE TABLE IF NOT EXISTS `user_browse_history` (
  `history_id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id` varchar(15) NOT NULL COMMENT '用户ID',
  `product_id` varchar(15) NOT NULL COMMENT '商品ID',
  `browse_time` datetime NOT NULL COMMENT '浏览时间',
  PRIMARY KEY (`history_id`),
  UNIQUE KEY `uk_browse_user_product` (`user_id`,`product_id`),
  KEY `idx_browse_user_time` (`user_id`,`browse_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='用户浏览历史';

CREATE TABLE IF NOT EXISTS `user_member_profile` (
  `user_id` varchar(15) NOT NULL,
  `level_code` tinyint NOT NULL DEFAULT '1' COMMENT '等级 1起',
  `growth_value` int NOT NULL DEFAULT '0' COMMENT '成长值',
  `level_name` varchar(30) DEFAULT NULL,
  `update_time` datetime DEFAULT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='会员档案';

CREATE TABLE IF NOT EXISTS `user_notification` (
  `notification_id` varchar(32) NOT NULL,
  `user_id` varchar(15) NOT NULL,
  `title` varchar(100) NOT NULL,
  `content` varchar(500) DEFAULT NULL,
  `biz_type` varchar(30) DEFAULT NULL COMMENT 'order/coupon/system',
  `biz_id` varchar(32) DEFAULT NULL,
  `read_status` tinyint(1) NOT NULL DEFAULT '0' COMMENT '0未读 1已读',
  `create_time` datetime NOT NULL,
  PRIMARY KEY (`notification_id`),
  KEY `idx_notification_user_read` (`user_id`,`read_status`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='站内通知';

CREATE TABLE IF NOT EXISTS `user_product_favorite` (
  `favorite_id` varchar(32) NOT NULL COMMENT '主键ID',
  `user_id` varchar(15) NOT NULL COMMENT '用户ID',
  `product_id` varchar(15) NOT NULL COMMENT '商品ID',
  `create_time` datetime NOT NULL COMMENT '收藏时间',
  PRIMARY KEY (`favorite_id`),
  UNIQUE KEY `uk_favorite_user_product` (`user_id`,`product_id`),
  KEY `idx_favorite_user_time` (`user_id`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='商品收藏';
