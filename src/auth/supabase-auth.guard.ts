import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import type { Request } from 'express';
import { SupabaseService } from '../supabase/supabase.service.js';

/**
 * Authenticates any valid Supabase user and attaches them to the request as
 * `request.user`. Ownership of individual resources (which rows a user may
 * read/write) is enforced by the services, not here — this guard only
 * answers "is this a real, logged-in user", not "which tenant are they".
 */
@Injectable()
export class SupabaseAuthGuard implements CanActivate {
  constructor(private readonly supabase: SupabaseService) {}

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

    (request as Request & { user: typeof data.user }).user = data.user;
    return true;
  }
}
