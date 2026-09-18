export const TRIAL_VISITOR = {
  email: 'visitor@smartlect.demo',
  password: 'Visit-Smartlect-2026',
  label: '作品集访客'
} as const;

export const DEMO_SHOPPER = {
  email: 'shopper@smartlect.demo',
  password: 'Visit-Smartlect-2026',
  label: '演示买家'
} as const;

export const TRIAL_USER_DENIED = '作品集试用账号只能浏览店内商品和导购，不能下单、加购、改密或改资料。';
export const DEMO_SHOPPER_DENIED = '演示买家账号不能改密、改资料或注册新号。';
export const PUBLIC_REGISTER_ENABLED = false;

export function isPublishedDemoLogin(email: string, password: string): boolean {
  const normalized = email.trim().toLowerCase();
  return (normalized === TRIAL_VISITOR.email && password === TRIAL_VISITOR.password)
    || (normalized === DEMO_SHOPPER.email && password === DEMO_SHOPPER.password);
}
