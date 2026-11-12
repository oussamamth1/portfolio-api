import { InternalServerErrorException, NotFoundException } from '@nestjs/common';
import { SupabaseService } from '../supabase/supabase.service.js';

export abstract class SupabaseCrudService<T extends { id: string }> {
  protected constructor(
    protected readonly supabase: SupabaseService,
    private readonly table: string,
    private readonly orderBy: string = 'sort_order',
  ) {}

  /** Rows owned by `userId` — used for both the authenticated "my own data"
   * routes and the public "by username" routes (the caller resolves
   * username -> userId before calling this). */
  async findAllFor(userId: string): Promise<T[]> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .select('*')
      .eq('user_id', userId)
      .order(this.orderBy, { ascending: true });
    if (error) throw new InternalServerErrorException(error.message);
    return data as T[];
  }

  async create(userId: string, payload: object): Promise<T> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .insert({ ...payload, user_id: userId })
      .select()
      .single();
    if (error) throw new InternalServerErrorException(error.message);
    return data as T;
  }

  async update(userId: string, id: string, payload: object): Promise<T> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .update({ ...payload, updated_at: new Date().toISOString() })
      .eq('id', id)
      .eq('user_id', userId)
      .select()
      .maybeSingle();
    if (error) throw new InternalServerErrorException(error.message);
    if (!data) throw new NotFoundException(`${this.table} record ${id} not found`);
    return data as T;
  }

  async remove(userId: string, id: string): Promise<void> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .delete()
      .eq('id', id)
      .eq('user_id', userId)
      .select('id')
      .maybeSingle();
    if (error) throw new InternalServerErrorException(error.message);
    if (!data) throw new NotFoundException(`${this.table} record ${id} not found`);
  }
}
