import { IsArray, IsInt, IsOptional, IsString } from 'class-validator';

export class CreateEducationDto {
  @IsString()
  institution!: string;

  @IsString()
  degree!: string;

  @IsOptional()
  @IsString()
  location?: string;

  @IsOptional()
  @IsString()
  period?: string;

  @IsOptional()
  @IsString()
  status?: string;

  @IsOptional()
  @IsString()
  description?: string;

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  coursework?: string[];

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  achievements?: string[];

  @IsOptional()
  @IsInt()
  sort_order?: number;
}
