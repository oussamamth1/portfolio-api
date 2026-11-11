import {
  CanActivate,
  ExecutionContext,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Request } from 'express';
import { SupabaseService } from '../supabase/supabase.service.js';

@Injectable()
export class SupabaseAuthGuard implements CanActivate {
  constructor(
    private readonly supabase: SupabaseService,
    private readonly config: ConfigService,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<Request>();
    const authHeader = request.headers['authorization'];
    const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : undefined;
    if (!token) {
      throw new UnauthorizedException('Missing bearer token');
    }

    const { data, error } = await this.supabase.client.auth.getUser(token);
    if (error || !data.user) {
      throw new UnauthorizedException('Invalid or expired token');
    }

    const adminEmail = this.config.get<string>('ADMIN_EMAIL');
    if (adminEmail && data.user.email !== adminEmail) {
      throw new UnauthorizedException('Not authorized to edit this profile');
    }

    (request as Request & { user: typeof data.user }).user = data.user;
    return true;
  }
}
