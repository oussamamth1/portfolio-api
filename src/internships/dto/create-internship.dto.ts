import {
  IsArray,
  IsBoolean,
  IsInt,
  IsOptional,
  IsString,
  IsUrl,
} from 'class-validator';

export class CreateInternshipDto {
  @IsString()
  company!: string;

  @IsString()
  role!: string;

  @IsOptional()
  @IsString()
  period?: string;

  @IsOptional()
  @IsString()
  location?: string;

  @IsOptional()
  @IsString()
  type?: string;

  @IsOptional()
  @IsBoolean()
  is_current?: boolean;

  @IsOptional()
  @IsString()
  description?: string;

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  highlights?: string[];

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  techs?: string[];

  @IsOptional()
  @IsUrl()
  logo_url?: string;

  @IsOptional()
  @IsUrl()
  demo_url?: string;

  @IsOptional()
  @IsString()
  video_id?: string;

  @IsOptional()
  @IsInt()
  sort_order?: number;
}
