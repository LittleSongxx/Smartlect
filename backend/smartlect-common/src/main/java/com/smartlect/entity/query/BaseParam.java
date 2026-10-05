package com.smartlect.entity.query;


/**
 * 查询参数基类。SQL 分页唯一机制是 PageHelper（见 PageUtils）：
 * pageNo/pageSize 由 PageUtils.page/pageInfo 消费。历史上还有
 * simplePage + mapper 手写 LIMIT 的分页路径，两套机制混用会拼出
 * 「limit ?,? LIMIT ?」非法 SQL（v15 线上 loadCommendProduct 事故），
 * 已随 BaseParam.simplePage 字段一并删除——编译期杜绝复发。
 */
public class BaseParam {
	private Integer pageNo;
	private Integer pageSize;
	private SafeSort orderBy;

	public Integer getPageNo() {
		return pageNo;
	}

	public void setPageNo(Integer pageNo) {
		this.pageNo = pageNo;
	}

	public Integer getPageSize() {
		return pageSize;
	}

	public void setPageSize(Integer pageSize) {
		this.pageSize = pageSize;
	}

	public void setOrderBy(SafeSort orderBy){
		this.orderBy = orderBy;
	}

	public SafeSort getOrderBy(){
		return this.orderBy;
	}
}
