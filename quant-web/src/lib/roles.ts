import type { Role } from '../types';

/** 角色常量（与后端 main.py 保持一致） */
export const ROLE_USER: Role = 'user';
export const ROLE_ADVANCED: Role = 'advanced';
export const ROLE_ADMIN: Role = 'admin';

export const ROLE_LABELS: Record<Role, string> = {
  user: '普通用户',
  advanced: '高级用户',
  admin: '超管',
};
