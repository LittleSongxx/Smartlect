-- Seata AT metadata must exist before its DataSource proxy initializes.
-- Adapted from the frozen Seata client schema; business tables remain Flyway-owned.
CREATE TABLE IF NOT EXISTS smartlect_order.undo_log (
    branch_id BIGINT NOT NULL,
    xid VARCHAR(128) NOT NULL,
    context VARCHAR(128) NOT NULL,
    rollback_info LONGBLOB NOT NULL,
    log_status INT NOT NULL,
    log_created DATETIME(6) NOT NULL,
    log_modified DATETIME(6) NOT NULL,
    UNIQUE KEY ux_undo_log (xid, branch_id),
    KEY ix_log_created (log_created)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AT transaction mode undo table';

CREATE TABLE IF NOT EXISTS smartlect_stock.undo_log LIKE smartlect_order.undo_log;
CREATE TABLE IF NOT EXISTS smartlect_coupon.undo_log LIKE smartlect_order.undo_log;
CREATE TABLE IF NOT EXISTS smartlect_cart.undo_log LIKE smartlect_order.undo_log;
CREATE TABLE IF NOT EXISTS smartlect_pay.undo_log LIKE smartlect_order.undo_log;
CREATE TABLE IF NOT EXISTS smartlect_user.undo_log LIKE smartlect_order.undo_log;
CREATE TABLE IF NOT EXISTS smartlect_product.undo_log LIKE smartlect_order.undo_log;
CREATE TABLE IF NOT EXISTS smartlect_admin.undo_log LIKE smartlect_order.undo_log;
