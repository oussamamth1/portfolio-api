import { InternalServerErrorException, NotFoundException } from '@nestjs/common';
import { SupabaseService } from '../supabase/supabase.service.js';

export abstract class SupabaseCrudService<T extends { id: string }> {
  protected constructor(
    protected readonly supabase: SupabaseService,
    private readonly table: string,
    private readonly orderBy: string = 'sort_order',
  ) {}

  async findAll(): Promise<T[]> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .select('*')
      .order(this.orderBy, { ascending: true });
    if (error) throw new InternalServerErrorException(error.message);
    return data as T[];
  }

  async create(payload: object): Promise<T> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .insert(payload)
      .select()
      .single();
    if (error) throw new InternalServerErrorException(error.message);
    return data as T;
  }

  async update(id: string, payload: object): Promise<T> {
    const { data, error } = await this.supabase.client
      .from(this.table)
      .update({ ...payload, updated_at: new Date().toISOString() })
      .eq('id', id)
      .select()
      .maybeSingle();
    if (error) throw new InternalServerErrorException(error.message);
    if (!data) throw new NotFoundException(`${this.table} record ${id} not found`);
    return data as T;
  }

  async remove(id: string): Promise<void> {
    const { error } = await this.supabase.client.from(this.table).delete().eq('id', id);
    if (error) throw new InternalServerErrorException(error.message);
  }
}
